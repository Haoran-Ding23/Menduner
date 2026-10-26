"""按城市导出公开活动周报（Excel MVP）。

## 边界（依据 GPT Round 2 审查 + 审核文档 §3）

1. **只读**：不写数据库、不改活动状态、无 schema 变更。
2. **鉴权**：路由用会话鉴权，不新建"公开可下载"的旁路。GET 只读但必须登录。
3. **不虚构变化**：没有可比快照时，「本期变化」写明不可用及原因，绝不把两份相邻日快照
   当成"一周变化"。
4. **不重复计数**：城市/区县/商圈用 `backend/geo.py` 的层级关系解析范围，按
   `canonical_id`（去重身份）计数一次；父级与其子级不会在同一次统计里各算一遍。
5. **字段白名单**：只输出允许公开的字段；内部审核记录、实体编号、核验方法等不进报表。
6. **公式注入防护**：所有外部文本按普通字符串写入，并对 `= + - @` 与前导空白做前缀转义；
   测试要求"保存后重新打开"时单元格 `data_type` 不是 `f`。

## 时间口径

日期一律是北京时间日期字符串（YYYY-MM-DD），与 `frontend/src/utils/caliber.ts` 的
`beijingToday` 语义一致：业务日期只跟城市有关，与读者时区无关。这里只接受日期，不接受
带时区的时间戳，避免"两个今天"。

活动筛选用**区间相交**：活动的 [startDate, endDate] 与查询区间有交集即纳入，因此跨年展览会
同时出现在两个区间的结果里，但在同一份报表内只算一个活动。
"""
from __future__ import annotations

import io
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

from backend import geo
from backend.version import CALIBER_VERSION
from backend.database import connect

# 单次导出上限：既是防滥用，也让"生成失败要给明确错误"有确定边界。
MAX_RANGE_DAYS = 366
MAX_ROWS = 5000

# 允许公开的字段（白名单）。凡不在这里的字段一律不进报表。
PUBLIC_EVENT_FIELDS = ("name", "category", "startDate", "endDate", "venueName", "districtName")

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# Excel 会把以这些字符开头的单元格当公式；前导空白后跟它们同样危险。
_FORMULA_PREFIX = ("=", "+", "-", "@", "\t", "\r")


class ReportError(ValueError):
    """输入或范围不合法；路由据此返回 4xx 而不是一份残缺的 Excel。"""


def safe_text(value: object) -> str:
    """把任意外部文本变成安全的普通字符串单元格值。

    先去掉控制字符，再对可能被 Excel 解释为公式的前缀加单引号 —— openpyxl 写入时仍按字符串，
    但我们同时保证"值本身"不刺激 Excel 解析。
    """
    if value is None:
        return ""
    text = _CONTROL.sub("", str(value)).strip()
    stripped = text.lstrip()
    if stripped.startswith(_FORMULA_PREFIX):
        return "'" + text
    return text


def parse_range(start: str | None, end: str | None, today: str | None = None) -> tuple[str, str]:
    """校验并规范化查询区间。默认最近 7 天（含今天）。"""
    today_value = today or _beijing_today()
    start_date = start or _shift(today_value, -6)
    end_date = end or today_value
    for label, value in (("开始日期", start_date), ("结束日期", end_date)):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value or ""):
            raise ReportError(f"{label}必须是 YYYY-MM-DD（当前 {value!r}）")
        try:
            date.fromisoformat(value)
        except ValueError as error:
            raise ReportError(f"{label}不是合法日期：{value}") from error
    if start_date > end_date:
        raise ReportError("开始日期不能晚于结束日期")
    span = (date.fromisoformat(end_date) - date.fromisoformat(start_date)).days + 1
    if span > MAX_RANGE_DAYS:
        raise ReportError(f"查询区间过长（{span} 天，上限 {MAX_RANGE_DAYS} 天）")
    return start_date, end_date


def _beijing_today() -> str:
    from datetime import timedelta

    return (datetime.now(timezone.utc) + timedelta(hours=8)).date().isoformat()


def _shift(value: str, days: int) -> str:
    from datetime import timedelta

    return (date.fromisoformat(value) + timedelta(days=days)).isoformat()


def scope_ids(db_path: Path, district_id: str) -> set[str]:
    """解析统计范围：该地区自身 + 其所有子级（按 geo 层级），不跨父级重复计入。"""
    districts, _events, _venues, _hotels = geo.load(db_path)
    if district_id not in districts:
        raise ReportError(f"地区不存在：{district_id}")
    selected = {district_id}
    changed = True
    while changed:
        changed = False
        for identifier, district in districts.items():
            if identifier in selected:
                continue
            if district.get("parentId") in selected:
                selected.add(identifier)
                changed = True
    return selected


def _overlaps(start: str | None, end: str | None, window_start: str, window_end: str) -> bool:
    if not start:
        return False
    finish = end or start
    if finish < start:  # 数据里出现倒置日期时按单日处理，不猜
        finish = start
    return start <= window_end and finish >= window_start


def _days_covered(start: str | None, end: str | None, window_start: str, window_end: str) -> int:
    if not start:
        return 0
    finish = end or start
    if finish < start:
        finish = start
    low = max(start, window_start)
    high = min(finish, window_end)
    if low > high:
        return 0
    return (date.fromisoformat(high) - date.fromisoformat(low)).days + 1


def collect(db_path: Path, district_id: str, start: str | None = None,
            end: str | None = None, today: str | None = None) -> dict:
    """收集报表数据。纯读，可供测试直接调用（不经过 HTTP）。"""
    window_start, window_end = parse_range(start, end, today)
    scope = scope_ids(db_path, district_id)

    with connect(db_path) as con:
        district_payload = json.loads(
            con.execute("SELECT payload FROM districts WHERE id=?", (district_id,)).fetchone()["payload"])
        venues = {row["id"]: json.loads(row["payload"])
                  for row in con.execute("SELECT id, payload FROM venues")}
        districts = {row["id"]: json.loads(row["payload"])
                     for row in con.execute("SELECT id, payload FROM districts")}
        columns = {row[1] for row in con.execute("PRAGMA table_info(events)")}
        has_canonical = "canonical_id" in columns
        canonical = "COALESCE(canonical_id, id)" if has_canonical else "id"

        rows = list(con.execute(
            f"SELECT id, {canonical} AS identity, name, category, startDate, endDate, venue, "
            "district, source, verification_status FROM events ORDER BY startDate"))

        # 同一身份只保留一条代表（规范记录），与前端 distinctByCanonical 口径一致
        chosen: dict[str, dict] = {}
        for row in rows:
            identity = row["identity"]
            current = chosen.get(identity)
            if current is None or row["id"] == identity:
                chosen[identity] = dict(row)

        in_scope = [event for event in chosen.values() if event["district"] in scope]
        in_window = [event for event in in_scope
                     if _overlaps(event["startDate"], event["endDate"], window_start, window_end)]

        sources = {row["id"]: dict(row) for row in con.execute("SELECT * FROM sources")}

    detail = []
    for event in in_window:
        venue = venues.get(event["venue"] or "") or {}
        district = districts.get(event["district"] or "") or {}
        detail.append({
            "identity": event["identity"],
            "name": event["name"],
            "category": event["category"],
            "startDate": event["startDate"],
            "endDate": event["endDate"],
            "venueName": venue.get("name"),
            "districtName": district.get("name"),
            "hasCoordinates": (venue.get("coordinates") or {}).get("lng") is not None,
            "source": event["source"],
            "status": event["verification_status"],
            "daysCovered": _days_covered(event["startDate"], event["endDate"], window_start, window_end),
        })

    if len(detail) > MAX_ROWS:
        raise ReportError(f"结果过多（{len(detail)} 条，上限 {MAX_ROWS}）；请缩小日期或地区范围")

    pending = []
    for event in in_window:
        reasons = []
        if not event["venue"]:
            reasons.append("未关联场馆")
        elif not ((venues.get(event["venue"]) or {}).get("coordinates") or {}).get("lng"):
            reasons.append("场馆缺少已核验坐标")
        if not event["startDate"]:
            reasons.append("开始日期缺失")
        if not event["endDate"]:
            reasons.append("结束日期缺失（按单日活动处理）")
        if event["verification_status"] == "Conflicting":
            reasons.append("来源之间存在日期或地点冲突")
        if reasons:
            pending.append({"name": event["name"], "reason": "；".join(reasons)})

    evidence = []
    for event in in_window:
        source = sources.get(event["source"] or "") or {}
        evidence.append({
            "name": event["name"],
            "sourceName": source.get("name") or event["source"],
            "sourceUrl": source.get("source_url"),
            "checkedAt": (source.get("updated_at") or "")[:10] or None,
            "publicStatus": _public_status(event["verification_status"]),
        })

    # 变化差分必须按本次统计范围过滤，否则别的城市的活动消失会被记成本城变化。
    scope_identities = {event["identity"] for event in chosen.values()
                        if event["district"] in scope}
    changes = _change_rows(db_path, window_start, window_end, scope_identities)

    return {
        "meta": {
            "districtId": district_id,
            "districtName": district_payload.get("name"),
            "level": district_payload.get("kind"),
            "window": {"start": window_start, "end": window_end},
            "uniqueActivities": len(detail),
            "activityDays": sum(event["daysCovered"] for event in detail),
            "sourceCount": len({event["source"] for event in in_window}),
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "dataThrough": max((event["startDate"] or "" for event in in_window), default="") or None,
            "batch": "公开活动快照（按去重身份计数，只读）",
            "caliberVersion": CALIBER_VERSION,
            "scopeSize": len(scope),
        },
        "detail": detail,
        "changes": changes,
        "evidence": evidence,
        "pending": pending,
        "limits": {"maxRangeDays": MAX_RANGE_DAYS, "maxRows": MAX_ROWS},
    }


def _public_status(status: str | None) -> str:
    """把内部核验状态映射成可对外的说法；内部枚举不外泄。"""
    return {
        "Verified": "已核验",
        "Needs Review": "待核对",
        "Conflicting": "存在冲突",
        "Missing": "信息缺失",
    }.get(status or "", "待核对")


def _change_rows(db_path: Path, window_start: str, window_end: str,
                 scope_identities: set[str] | None = None) -> dict:
    """本期变化：只在该区间内确实存在两份以上快照时才给差分。"""
    from backend import tracking

    try:
        snapshot_dates = [value for value in tracking.snapshot_dates(db_path)
                          if window_start <= value <= window_end]
    except Exception:  # 未迁移的库没有快照表
        snapshot_dates = []

    if len(snapshot_dates) < 2:
        return {
            "available": False,
            "reason": ("缺少可比历史数据，暂不提供变化统计"
                       if not snapshot_dates
                       else f"区间内只有 {len(snapshot_dates)} 份快照（{snapshot_dates[0]}），无法差分"),
            "coverage": {"from": snapshot_dates[0] if snapshot_dates else None,
                         "to": snapshot_dates[-1] if snapshot_dates else None},
            "rows": [],
        }

    result = tracking.changes(db_path, snapshot_dates[0], until=window_end)
    if not result.get("comparable"):
        return {"available": False, "reason": result.get("reason", "快照不可比较"),
                "coverage": {"from": snapshot_dates[0], "to": snapshot_dates[-1]}, "rows": []}

    rows: list[dict] = []
    for item in result.get("added", []):
        rows.append({"kind": "新增", "name": item.get("name"), "note": item.get("start_date") or "", "identity": item.get("event_key")})
    for item in result.get("rescheduled", []):
        before = item.get("before") or {}
        after = item.get("after") or {}
        rows.append({"kind": "改期", "name": after.get("name"),
                     "note": f"{before.get('start_date') or '?'} → {after.get('start_date') or '?'}",
                     "identity": after.get("event_key")})
    for item in result.get("cancelled", []):
        rows.append({"kind": "消失", "name": item.get("name"),
                     "note": "本次快照中未出现；可能是活动取消，也可能是采集未覆盖，需人工确认",
                     "identity": item.get("event_key")})
    for item in result.get("changed", []):
        rows.append({"kind": "信息更新", "name": (item.get("after") or {}).get("name"), "note": "", "identity": (item.get("after") or {}).get("event_key")})
    if scope_identities is not None:
        rows = [row for row in rows if row.get("identity") in scope_identities]
    return {
        "available": True,
        "reason": None,
        "coverage": {"from": result.get("from"), "to": result.get("to"),
                     "snapshotDates": snapshot_dates},
        "rules": ("新增=基线与截止两次快照间首次出现；消失=截止快照未出现（不直接判定取消）；"
                      "改期=起止日期变化；信息更新=名称或状态变化"),
        "rows": rows,
    }


# --- Excel -------------------------------------------------------------------------------

def build_xlsx(report: dict) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    book = Workbook()
    head = Font(bold=True)
    meta = report["meta"]

    overview = book.active
    overview.title = "城市概览"
    overview.append(["城市活动简报"])
    overview.cell(row=1, column=1).font = Font(bold=True, size=14)
    for label, value in [
        ("地区", meta["districtName"]),
        ("地区类型", {"city": "地级市", "county_city": "县级市", "district": "市辖区"}.get(
            meta["level"] or "", "其他")),
        ("查询区间", f"{meta['window']['start']} 至 {meta['window']['end']}"),
        ("唯一活动数（去重身份）", meta["uniqueActivities"]),
        ("活动覆盖天数（同一活动跨天只按天累计）", meta["activityDays"]),
        ("来源数", meta["sourceCount"]),
        ("统计范围（含子级地区数）", meta["scopeSize"]),
        ("数据批次", meta["batch"]),
        ("口径版本", meta.get("caliberVersion")),
        ("数据截至", meta["dataThrough"] or "未知"),
        ("生成时间（UTC）", meta["generatedAt"][:19].replace("T", " ")),
        ("时间口径", "北京时间；日期区间相交即纳入，跨年活动在各自区间各出现一次"),
    ]:
        overview.append([label, safe_text(value)])
    overview.append([])
    overview.append(["说明", safe_text("本报表只含公开活动数据，不含酒店经营数据、私人跟进或账号信息。")])

    detail = book.create_sheet("活动明细")
    # 不输出规范化身份（内部 canonical_id）：去重仍用身份，但下载者不需要看到数据库主键。
    detail.append(["活动名称", "类别", "开始", "结束", "场馆", "地区",
                   "覆盖天数", "坐标", "主要来源", "对外状态"])
    for cell in detail[1]:
        cell.font = head
    for row in report["detail"]:
        detail.append([
            safe_text(row["name"]), safe_text(row["category"]),
            safe_text(row["startDate"]), safe_text(row["endDate"]),
            safe_text(row["venueName"] or "未关联"), safe_text(row["districtName"]),
            row["daysCovered"], "有" if row["hasCoordinates"] else "缺",
            safe_text(row["source"]), safe_text(_public_status(row["status"])),
        ])

    changes = book.create_sheet("本期变化")
    changes.append(["本期变化"])
    changes.cell(row=1, column=1).font = head
    if report["changes"]["available"]:
        coverage = report["changes"]["coverage"]
        changes.append(["比较区间", safe_text(f"{coverage['from']} → {coverage['to']}（实际快照区间，非自然周）")])
        changes.append(["判定规则", safe_text(report["changes"].get("rules", ""))])
        changes.append([])
        changes.append(["类型", "活动", "说明"])
        for cell in changes[changes.max_row]:
            cell.font = head
        for row in report["changes"]["rows"]:
            changes.append([safe_text(row["kind"]), safe_text(row["name"]), safe_text(row["note"])])
    else:
        changes.append(["不可用", safe_text(report["changes"]["reason"])])
        coverage = report["changes"]["coverage"]
        if coverage.get("from"):
            changes.append(["已有快照", safe_text(f"{coverage['from']} → {coverage['to']}")])

    evidence = book.create_sheet("来源证据")
    evidence.append(["活动", "来源名称", "公开 URL", "最近核对", "对外状态"])
    for cell in evidence[1]:
        cell.font = head
    for row in report["evidence"]:
        # URL 一律按普通文本写入，不生成超链接对象，避免未审查的可执行链接行为。
        evidence.append([safe_text(row["name"]), safe_text(row["sourceName"]),
                         safe_text(row["sourceUrl"]), safe_text(row["checkedAt"]),
                         safe_text(row["publicStatus"])])

    pending = book.create_sheet("待确认事项")
    pending.append(["活动", "待确认原因"])
    for cell in pending[1]:
        cell.font = head
    if report["pending"]:
        for row in report["pending"]:
            pending.append([safe_text(row["name"]), safe_text(row["reason"])])
    else:
        pending.append(["无", "本区间内没有待确认事项"])

    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()
