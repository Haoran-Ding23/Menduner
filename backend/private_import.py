"""Bring a hotel's own spreadsheet into its private ledger.

## Why this exists

A hotel will not reshape its data to suit us. Its file has its own headers, its own month
format, its own idea of what a column is called - 出租率, 入住率, Occ%, 入住率(%) are the same
thing and all four appear in real exports. Requiring a template would mean the customer does the
work and fails silently; so the import reads what they send, proposes a mapping, and shows what
it will store before storing anything.

## The shape of the flow

    bytes ──parse──▶ headers + rows ──detect──▶ suggested mapping
                                           │
                              human confirms / edits
                                           ▼
                        validate ──▶ accepted rows + per-row issues
                                           ▼
                                 written into this tenant's own database

Nothing is written until the caller has seen the preview: a wrong mapping silently applied would
put an occupancy figure in the ADR column, and the hotel would only notice when the numbers
looked odd. The preview is the contract.

## What it refuses

  * a file whose header cannot be mapped to a known metric - better to say so than to guess;
  * a percentage outside 0-100, a date that is not a date, a non-numeric value;
  * a row with no period.
Per-row refusals come back as issues with the row number so the customer can fix their file;
they are never silently dropped, because a silent drop is indistinguishable from success.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime

# Header aliases seen in real hotel exports, by metric. Matching is case-insensitive after
# removing spaces, punctuation and bracketed units, so 入住率(%), OCCUPANCY, 出租率 all land on
# the same metric.
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "occupancy_pct": (
        "入住率", "出租率", "开房率", "occupancy", "occupancyrate", "occ", "oCC",
        "occupancypct", "出租率pct",
    ),
    "adr": (
        "平均房价", "房价", "adr", "averagedailyrate", "平均房价元", "均价",
    ),
    "room_nights": (
        "间夜", "间夜数", "房晚", "roomnights", "roomnights", "nights", "已售间夜",
    ),
    "channel_share": (
        "渠道占比", "渠道比例", "渠道", "channelshare", "channel", "渠道占比pct",
    ),
    "room_type_share": (
        "房型结构", "房型占比", "房型比例", "roomtypeshare", "roomtype", "房型",
    ),
}

# The date column is not a metric: it locates the row.
PERIOD_ALIASES = (
    "日期", "统计日期", "时间", "月份", "period", "date", "month", "周期",
)

# Extra headers that refine a row without being the value itself.
CHANNEL_ALIASES = ("渠道", "渠道名称", "channel", "channelname")
ROOM_TYPE_ALIASES = ("房型", "房型名称", "roomtype", "roomtypename")
END_ALIASES = ("结束日期", "截止日期", "enddate", "periodend")

_UNIT = re.compile(r"[（(]\s*(?:%|％|元|间|天|间夜)\s*[)）]")
_NOISE = re.compile(r"[\s\-_/·．.，,、:：|]+")


def normalise_header(value: str) -> str:
    """A header reduced to what it means: no spaces, no units, no punctuation, lower-case."""
    text = _UNIT.sub("", (value or "").strip())
    text = _NOISE.sub("", text)
    return text.casefold()


def detect_mapping(headers: list[str]) -> dict[str, int]:
    """Suggest which column holds what.

    Returns ``{role: column index}`` where role is a metric name, ``period``, ``channel``,
    ``room_type`` or ``period_end``. A header matched by nothing is simply absent from the
    result, so the caller can show the customer what was not understood instead of guessing.
    """
    mapping: dict[str, int] = {}
    used: set[int] = set()

    def claim(role: str, aliases: tuple[str, ...]) -> None:
        if role in mapping:
            return
        wanted = {normalise_header(a) for a in aliases}
        for index, header in enumerate(headers):
            if index in used:
                continue
            if normalise_header(header) in wanted:
                mapping[role] = index
                used.add(index)
                return

    claim("period", PERIOD_ALIASES)
    claim("period_end", END_ALIASES)
    claim("channel", CHANNEL_ALIASES)
    claim("room_type", ROOM_TYPE_ALIASES)
    for metric in COLUMN_ALIASES:
        claim(metric, COLUMN_ALIASES[metric])
    return mapping


def parse_table(data: bytes, *, filename: str = "") -> tuple[list[str], list[list[str]]]:
    """Headers and rows from an uploaded CSV or XLSX.

    CSV is read with the standard library so the core path has no dependency. XLSX needs
    openpyxl; when it is missing the message says so plainly rather than failing with an
    import error from inside a request.
    """
    name = (filename or "").casefold()
    if name.endswith(".xlsx") or name.endswith(".xlsm"):
        try:
            import openpyxl  # type: ignore
        except ImportError:  # pragma: no cover - environment dependent
            raise ValueError(
                "Excel (.xlsx) import needs the openpyxl package on the server; "
                "export to CSV for now, or install openpyxl"
            ) from None
        book = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        sheet = book.active
        rows = []
        for row in sheet.iter_rows(values_only=True):
            rows.append(["" if cell is None else str(cell) for cell in row])
        book.close()
        rows = [r for r in rows if any(c.strip() for c in r)]
        if not rows:
            raise ValueError("The spreadsheet is empty")
        return rows[0], rows[1:]

    text = data.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    rows = [r for r in reader if any(c.strip() for c in r)]
    if not rows:
        raise ValueError("The file is empty")
    return rows[0], rows[1:]


_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def parse_number(raw: str) -> float | None:
    """A number from a cell that may carry a currency mark, percent sign or thousands
    separators. Searching rather than matching is deliberate: exports prefix values with ￥ and
    元 sits on either side depending on the layout."""
    text = (raw or "").strip().replace(",", "").replace("，", "")
    if not text:
        return None
    for symbol in ("%", "％", "元", "¥", "￥", "RMB", "rmb"):
        text = text.replace(symbol, "")
    match = _NUMBER.search(text)
    return float(match.group(0)) if match else None


_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d", "%Y-%m", "%Y年%m月", "%Y年%m月%d日")
# Range separators that cannot appear inside a date. A hyphen is not one of them: it is the
# separator in 2026-10-01, so splitting on it first turned every ISO date into three pieces.
_RANGE_SEPARATORS = ("至", "~", "～", "到", "—", "–", " - ")


def _one_date(chunk: str) -> str | None:
    chunk = (chunk or "").strip()
    if not chunk:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(chunk, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def parse_period(raw: str) -> tuple[str, str | None]:
    """The period's start date, and the end date when the cell states a range.

    Returns ``(start, end)`` as YYYY-MM-DD, or ``("", None)`` when the cell is not a date.
    """
    text = (raw or "").strip()
    if not text:
        return "", None
    whole = _one_date(text)
    if whole:
        return whole, None
    for separator in _RANGE_SEPARATORS:
        if separator in text:
            left, _, right = text.partition(separator)
            start = _one_date(left)
            if start:
                return start, _one_date(right)
    return "", None


def build_preview(headers: list[str], rows: list[list[str]],
                  mapping: dict[str, int]) -> dict:
    """What the import would store, and what it cannot.

    The caller shows this to the customer before anything is written. Every refused row comes
    back with its spreadsheet row number and the reason, so the file can be fixed rather than
    guessed at.
    """
    metrics = [role for role in mapping if role in COLUMN_ALIASES]
    if "period" not in mapping:
        raise ValueError("No date column was mapped; a measurement needs a period")
    if not metrics:
        raise ValueError(
            "No metric column was mapped; map at least one of: "
            + ", ".join(COLUMN_ALIASES)
        )

    accepted: list[dict] = []
    issues: list[dict] = []
    for offset, row in enumerate(rows, start=2):  # row 1 is the header
        def cell(role: str) -> str:
            index = mapping.get(role)
            if index is None or index >= len(row):
                return ""
            return (row[index] or "").strip()

        start, end = parse_period(cell("period"))
        if not start:
            issues.append({"row": offset, "reason": f"日期无法识别：{cell('period') or '(空)'}"})
            continue
        if not end:
            stated = parse_period(cell("period_end"))[0] if "period_end" in mapping else ""
            end = stated or None

        made = 0
        for metric in metrics:
            raw = cell(metric)
            if not raw:
                continue
            value = parse_number(raw)
            if value is None:
                issues.append({"row": offset,
                               "reason": f"{metric} 不是数字：{raw}"})
                continue
            if metric in ("occupancy_pct", "channel_share", "room_type_share") \
                    and not (0 <= value <= 100):
                issues.append({"row": offset,
                               "reason": f"{metric} 应在 0–100 之间：{value}"})
                continue
            accepted.append({
                "metric": metric,
                "period_start": start,
                "period_end": end,
                "value": value,
                "channel": cell("channel") or None,
                "room_type": cell("room_type") or None,
            })
            made += 1
        if made == 0 and not any(i["row"] == offset for i in issues):
            issues.append({"row": offset, "reason": "该行没有可导入的数值"})

    return {
        "headers": headers,
        "mapping": mapping,
        "metrics": metrics,
        "rows_read": len(rows),
        "accepted": accepted,
        "issues": issues,
    }


def commit_preview(con, preview: dict, *, uploaded_by: str,
                   source_file: str | None = None) -> int:
    """Write an accepted preview into the tenant's private database."""
    from backend.tenants import record_metric

    written = 0
    for row in preview["accepted"]:
        record_metric(
            con,
            metric=row["metric"],
            period_start=row["period_start"],
            period_end=row.get("period_end"),
            value=row["value"],
            channel=row.get("channel"),
            room_type=row.get("room_type"),
            uploaded_by=uploaded_by,
            source_file=source_file,
        )
        written += 1
    return written
