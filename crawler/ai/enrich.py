"""Read a stored evidence page with DeepSeek and use it two ways.

The model is a READER here, never an authority:

  * **extraction** — pull the factual fields a page states, so a source our rules rejected
    (``No explicit leading event date``) still contributes instead of being dropped;
  * **cross-check** — compare what the model read against what our extractor produced. Agreement
    raises confidence; disagreement is the interesting case and is surfaced to a human, which
    turns the model's unreliability into the thing that finds our mistakes.

Nothing here changes an event's verification status. A value the model found is a *suggestion*
attached to evidence; only the existing rules and a human reviewer can settle a field, because
a language model is not a citable source.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

from crawler.ai.client import DeepSeek, DeepSeekError

# What the model may report. Anything else is discarded rather than trusted.
FACT_FIELDS = ("event_name", "start_date", "end_date", "venue", "location", "organizer")

SYSTEM_PROMPT = """你是一个严谨的网页信息抽取器，为一个"可追溯城市活动情报"系统工作。

铁律（违反即视为抽取失败）：
1. 只抽取页面中**明确写出**的信息。绝对不要推断、不要补全、不要使用常识。
2. 任何页面里没有明确写出的字段，一律返回 null。宁可返回 null，也不要猜。
3. 每个抽出的字段必须附上页面中的**原文片段**作为证据（逐字复制，不要改写）。
4. 日期必须是页面明确写出的具体日期。相对时间（"下周六""本月"）一律返回 null。
   如果只写了月日没有年份，返回原始文本并把 certainty 标为 low。
5. 不要输出任何解释性文字，只输出 JSON。

输出 JSON 结构：
{
  "is_event": true/false,
  "event_name": {"value": "...", "evidence": "..."} 或 null,
  "start_date": {"value": "YYYY-MM-DD", "evidence": "..."} 或 null,
  "end_date": {"value": "YYYY-MM-DD", "evidence": "..."} 或 null,
  "venue": {"value": "...", "evidence": "..."} 或 null,
  "location": {"value": "...", "evidence": "..."} 或 null,
  "organizer": {"value": "...", "evidence": "..."} 或 null,
  "certainty": "high"/"medium"/"low",
  "note": "若判断该页面不是一个具体活动，在此说明原因"
}"""


class _Text(HTMLParser):
    """Strip markup but keep block boundaries, so dates and labels stay separable."""

    SKIP = {"script", "style", "noscript", "svg", "head"}
    BLOCK = {
        "p", "div", "li", "tr", "br", "h1", "h2", "h3", "h4", "h5", "h6",
        "td", "th", "section", "article", "table", "ul", "ol",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in self.SKIP:
            self._skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip and data.strip():
            self.parts.append(data)

    def text(self) -> str:
        raw = "".join(self.parts)
        raw = re.sub(r"[ \t\u3000]+", " ", raw)
        raw = re.sub(r"\n\s*\n+", "\n", raw)
        return raw.strip()


def readable_text(html: str, limit: int = 12000) -> str:
    """Page text for the model, bounded so one huge page cannot blow the token budget."""
    parser = _Text()
    try:
        parser.feed(html)
    except Exception:  # malformed markup must not lose the page
        pass
    text = parser.text()
    if len(text) > limit:
        # Keep the head and the tail: Chinese government pages put the payload in the body and
        # the contact/organiser block at the end.
        head, tail = limit * 3 // 4, limit // 4
        text = text[:head] + "\n…（中略）…\n" + text[-tail:]
    return text


@dataclass
class Finding:
    """One field the model read, with the quote that justifies it."""

    value: str | None
    evidence: str | None = None

    @property
    def present(self) -> bool:
        return bool(self.value and str(self.value).strip())


@dataclass
class Reading:
    url: str
    is_event: bool
    fields: dict[str, Finding] = field(default_factory=dict)
    certainty: str = "low"
    note: str | None = None
    raw: dict | None = None
    error: str | None = None

    def as_dict(self) -> dict:
        return {
            "url": self.url,
            "is_event": self.is_event,
            "certainty": self.certainty,
            "note": self.note,
            "error": self.error,
            "fields": {
                name: {"value": f.value, "evidence": f.evidence}
                for name, f in self.fields.items()
                if f.present
            },
        }


def _finding(entry) -> Finding:
    if not isinstance(entry, dict):
        return Finding(value=None)
    return Finding(
        value=entry.get("value"),
        evidence=entry.get("evidence") or entry.get("quote"),
    )


def read_page(client: DeepSeek, *, url: str, html: str) -> Reading:
    """Ask the model what this page states, with evidence for every field."""
    text = readable_text(html)
    if len(text) < 80:
        return Reading(url=url, is_event=False, note="页面正文过短，无可抽取内容")
    try:
        document = client.complete_json(
            system=SYSTEM_PROMPT,
            user=f"页面 URL：{url}\n\n页面正文：\n{text}",
            max_tokens=1500,
        )
    except DeepSeekError as exc:
        return Reading(url=url, is_event=False, error=str(exc))

    reading = Reading(
        url=url,
        is_event=bool(document.get("is_event")),
        certainty=str(document.get("certainty") or "low").lower(),
        note=document.get("note"),
        raw=document,
    )
    for name in FACT_FIELDS:
        reading.fields[name] = _finding(document.get(name))
    # A claim with no quote is not usable evidence: drop the value rather than trust it.
    for name, finding in reading.fields.items():
        if finding.present and not (finding.evidence and finding.evidence.strip()):
            reading.fields[name] = Finding(
                value=None,
                evidence=None,
            )
    return reading


# --- cross-check -----------------------------------------------------------------

DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _normalize_name(value) -> str:
    if not value:
        return ""
    from crawler.pipeline import identity_text

    return identity_text(value) or ""


def _normalize_date(value) -> str:
    if not value:
        return ""
    match = DATE.search(str(value))
    return f"{match.group(1)}-{match.group(2)}-{match.group(3)}" if match else ""


def compare(reading: Reading, extracted: dict) -> dict:
    """Agree/disagree per field between the model's reading and our extractor.

    ``disagree`` is the signal worth a human's time, but raw disagreement is mostly noise and
    must be filtered or the report is useless. Two false-positive families were measured on the
    real corpus and are classified separately rather than reported as findings:

      * ``split_differently`` — our extractor separates a venue from its street address
        (``venue`` + ``location``), the model writes the whole line into one field. Both read the
        page correctly; the disagreement is about where the boundary belongs.
      * ``ai_failed`` — the model returned nothing for a field while our extractor resolved it.
        Douban publishes 月日 without a year and the model is required to return null there,
        whereas our extractor resolves the year from the weekday.

    Only a residual disagreement — both read a value, and the values differ by more than the
    address/venue boundary — is reported as needing a human.
    """
    agree: dict[str, str] = {}
    disagree: dict[str, dict] = {}
    only_ai: dict[str, dict] = {}
    only_extractor: dict[str, str] = {}
    split_differently: dict[str, dict] = {}

    def combined(value) -> str:
        return _normalize_name(value)

    ours_location = combined(extracted.get("location"))
    ours_venue = combined(extracted.get("venue"))
    theirs_venue = combined(reading.fields.get("venue").value if reading.fields.get("venue") else None)
    theirs_location = combined(
        reading.fields.get("location").value if reading.fields.get("location") else None
    )

    for name in FACT_FIELDS:
        ours = extracted.get(name)
        ours_norm = _normalize_date(ours) if "date" in name else _normalize_name(ours)
        theirs = reading.fields.get(name)
        theirs_norm = (
            (_normalize_date(theirs.value) if "date" in name else _normalize_name(theirs.value))
            if theirs
            else ""
        )

        if not ours_norm and not theirs_norm:
            continue
        if ours_norm and not theirs_norm:
            only_extractor[name] = str(ours)
            continue
        if theirs_norm and not ours_norm:
            only_ai[name] = {"value": theirs.value, "evidence": theirs.evidence}
            continue
        if ours_norm == theirs_norm:
            agree[name] = str(ours)
            continue

        # The venue/address boundary: one side carries the venue name inside the address, or
        # vice versa. Comparing the two fields as a set catches it in both directions.
        if name in ("venue", "location"):
            our_side = {ours_venue, ours_location} - {""}
            their_side = {theirs_venue, theirs_location} - {""}
            if (
                all(any(a in b or b in a for b in their_side or {""}) for a in our_side)
                or all(any(b in a or a in b for a in our_side or {""}) for b in their_side)
            ):
                split_differently[name] = {
                    "extractor": str(ours),
                    "ai": theirs.value,
                    "ai_evidence": theirs.evidence,
                }
                continue

        disagree[name] = {
            "extractor": str(ours),
            "ai": theirs.value,
            "ai_evidence": theirs.evidence,
        }

    return {
        "agree": agree,
        "disagree": disagree,
        "only_ai": only_ai,
        "only_extractor": only_extractor,
        "split_differently": split_differently,
    }
