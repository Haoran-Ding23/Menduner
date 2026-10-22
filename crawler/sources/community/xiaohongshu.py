"""Manually authorised Xiaohongshu note import — MediaCrawler output into the pipeline.

This source is unlike every other registered source: **nothing is fetched here**. The
notes are collected out-of-band by ``tools/MediaCrawler`` under the operator's own
logged-in session (student / non-commercial research use, per its NON-COMMERCIAL
license), and this adapter only reads that output file. No HTTP request is made, no
login is performed, and no signature is produced by this repository.

The pipeline contract is unchanged. Each note that passes the deterministic pre-screen
becomes one :class:`CollectedItem` whose ``raw_content`` is the note's own title plus
body text, stored verbatim. The AI reading (``crawler.ai.enrich``, the same reader used
on evidence pages) travels in ``request_metadata``; the ``social_note_ai`` extractor
turns that reading into an event with the usual fail-closed rules:

* the note's **publish time is metadata only** and can never become an event date —
  the same rule that keeps bureau news columns and library archives out;
* a field exists only when the reading carries an explicit value **and** the verbatim
  quote that justifies it (``read_page`` already drops unsupported claims);
* ``start_date`` must be a year-bearing explicit date; month/day without a year is
  rejected, never repaired;
* the place must name Suzhou explicitly;
* the source carries no registry trust level, so ``verification.decide`` fails closed
  and every field lands in the human review queue — nothing from social notes is ever
  auto-Verified.
"""
from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from crawler.ai.enrich import read_page
from crawler.schema import CollectedItem

SOURCE_ID = "xiaohongshu-note-import"
SOURCE_NAME = "小红书笔记（MediaCrawler 导入）"
EXTRACTOR = "social_note_ai"

# A place signal must appear in the note before it is worth an AI reading. Explicit
# Suzhou names only — the generic "高新区" exists in every Chinese city and is excluded.
SUZHOU_SIGNALS = (
    "苏州", "姑苏", "虎丘", "吴中", "相城", "吴江", "工业园区",
    "昆山", "常熟", "太仓", "张家港",
)

# An explicit date WITH a year. Month/day without a year can never become a start_date
# (the enrichment prompt itself returns null there), so a note that only has one is not
# worth a reading. Kept in sync with the year-bearing forms the extractor accepts.
DATE_WITH_YEAR = re.compile(r"20\d{2}\s*[-./年]\s*\d{1,2}\s*[-./月]\s*\d{1,2}\s*日?")

# Certainty to confidence mapping. Capped below the deterministic extractors' 0.85:
# a language model reading is a suggestion with a quote, not a source field.
AI_CONFIDENCE = {"high": 0.7, "medium": 0.55, "low": 0.4}


def prescreen(text: str) -> tuple[bool, str]:
    """Deterministic gate before any AI token is spent.

    A note is an event candidate only when it names an explicit Suzhou place signal AND
    carries a year-bearing date. Event wording is deliberately not required here —
    recalls like "昨天去了…" matter less than missing a genuine announcement, and the
    AI reading's own ``is_event`` judgement is the noise filter.
    """
    if not any(signal in text for signal in SUZHOU_SIGNALS):
        return False, "no explicit Suzhou place signal"
    if not DATE_WITH_YEAR.search(text):
        return False, "no year-bearing explicit date"
    return True, "passed"


def note_date(value):
    """Normalise the enrichment prompt's date forms (``2026-10-21`` or ``2026年10月21日``).

    Returns the ISO form or None; a month/day without a year never resolves here.
    """
    if not isinstance(value, str):
        return None
    value = value.strip().replace("年", "-").replace("月", "-").replace("日", "")
    match = re.match(r"^(20\d{2})[-./](\d{1,2})[-./](\d{1,2})", value)
    if not match:
        return None
    return f"{int(match[1]):04}-{int(match[2]):02}-{int(match[3]):02}"


def load_notes(path: Path) -> list[dict]:
    """Read a MediaCrawler export (``.jsonl`` as saved by default, or ``.csv``)."""
    suffix = path.suffix.lower()
    rows: list[dict] = []
    if suffix == ".jsonl":
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    elif suffix == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows.extend(dict(row) for row in csv.DictReader(handle))
    else:
        raise ValueError(f"Unsupported MediaCrawler export format: {suffix} (use .jsonl or .csv)")
    seen: dict[str, dict] = {}
    for row in rows:
        note_id = str(row.get("note_id") or "").strip()
        if note_id:
            seen.setdefault(note_id, row)
    if not seen:
        raise ValueError("Export carries no note_id; not a MediaCrawler XHS note file")
    return list(seen.values())


class XiaohongshuImportAdapter:
    """One import run: reads the export file, pre-screens, attaches AI readings."""

    mock = False
    source_id = SOURCE_ID
    source_name = SOURCE_NAME
    kind = "social_media"
    source_url = "https://www.xiaohongshu.com"
    # No registry trust level by design: the auto-verification rule must treat this
    # source as non-authoritative, so every field it publishes stays pending.
    trust_level = None
    extractor = EXTRACTOR
    require_events = False

    def __init__(self, notes_path=None, ai_client=None, notes=None):
        self.notes_path = Path(notes_path) if notes_path else None
        self.ai_client = ai_client
        self._notes = notes
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.pages_collected = 0
        self.request_attempts = 0
        self.investigation: dict[str, int] = {}

    def collect(self) -> list[CollectedItem]:
        rows = self._notes if self._notes is not None else load_notes(self.notes_path)
        now = datetime.now(timezone.utc)
        items: list[CollectedItem] = []
        self.investigation = {"prescreenPassed": 0, "prescreenContext": 0, "aiReadings": 0, "aiFailures": 0}
        for row in rows:
            note_id = str(row.get("note_id") or "").strip()
            title = str(row.get("title") or "")
            desc = str(row.get("desc") or "")
            body = f"{title}\n{desc}".strip()
            if not note_id or not body:
                self.warnings.append(f"row without note_id or empty body skipped")
                continue
            note_url = (
                str(row.get("note_url") or "").strip()
                or f"https://www.xiaohongshu.com/explore/{note_id}"
            )
            tags = str(row.get("tag_list") or "")
            metadata = {
                # The publish timestamp is provenance, never an event date.
                "note_published_at": row.get("time"),
                "nickname": row.get("nickname"),
                "liked_count": row.get("liked_count"),
                "source_keyword": row.get("source_keyword"),
                "tag_list": tags,
            }
            ok, reason = prescreen(f"{title}\n{desc}\n{tags}")
            if not ok:
                self.investigation["prescreenContext"] += 1
                metadata["prescreen"] = reason
                items.append(
                    CollectedItem(
                        item_key=note_id,
                        original_url=note_url,
                        source_name=self.source_name,
                        crawl_time=now,
                        raw_content=body,
                        mock=False,
                        extractor=EXTRACTOR,
                        is_event=False,
                        request_metadata=metadata,
                    )
                )
                continue
            self.investigation["prescreenPassed"] += 1
            metadata["prescreen"] = "passed"
            reading = None
            if self.ai_client is not None:
                reading = read_page(self.ai_client, url=note_url, html=body, min_chars=30)
                if reading.error:
                    self.investigation["aiFailures"] += 1
                    self.warnings.append(f"{note_id}: AI reading failed: {reading.error}")
                else:
                    self.investigation["aiReadings"] += 1
            metadata["ai_reading"] = reading.as_dict() if reading else None
            items.append(
                CollectedItem(
                    item_key=note_id,
                    original_url=note_url,
                    source_name=self.source_name,
                    crawl_time=now,
                    raw_content=body,
                    mock=False,
                    extractor=EXTRACTOR,
                    is_event=True,
                    request_metadata=metadata,
                )
            )
        return items


def social_note_ai(item: CollectedItem):
    """Turn one attached AI reading into an event, failing closed at every step."""
    from crawler.extractor import base, full_date, set_field

    reading = (item.request_metadata or {}).get("ai_reading")
    if not reading:
        raise ValueError("No AI reading attached to this note; retained raw")
    if not reading.get("is_event"):
        raise ValueError("AI reading judged the note not a concrete event; retained raw")

    fields = reading.get("fields") or {}
    certainty = str(reading.get("certainty") or "low")
    confidence = AI_CONFIDENCE.get(certainty, AI_CONFIDENCE["low"])
    quality = dict(
        status="Needs Review",
        method="ai_note_extraction",
        confidence=confidence,
    )

    def finding(name):
        entry = fields.get(name) or {}
        return entry.get("value"), entry.get("evidence")

    name, name_quote = finding("event_name")
    start_raw, start_quote = finding("start_date")
    start = note_date(start_raw) or full_date(start_raw)
    if not name or not start:
        raise ValueError(
            "AI reading lacks an explicit event name or a year-bearing start date; retained raw"
        )
    venue, venue_quote = finding("venue")
    location, location_quote = finding("location")
    organizer, organizer_quote = finding("organizer")
    end_raw, end_quote = finding("end_date")
    end = note_date(end_raw) or full_date(end_raw)

    place_text = json.dumps([venue, location], ensure_ascii=False)
    if not any(signal in place_text for signal in SUZHOU_SIGNALS):
        raise ValueError("Social note place is not explicitly in Suzhou; retained raw")

    event = base(item)
    set_field(event, "event_name", name, snippet=name_quote, **quality)
    set_field(event, "start_date", start, snippet=start_quote, **quality)
    if end:
        set_field(event, "end_date", end, snippet=end_quote, **quality)
    if venue:
        set_field(event, "venue", venue, snippet=venue_quote, **quality)
    if location:
        set_field(event, "location", location, snippet=location_quote, **quality)
    if organizer:
        set_field(event, "organizer", organizer, snippet=organizer_quote, **quality)
    set_field(
        event,
        "category",
        "others",
        snippet="category_rule: social note, uncategorised pending review",
        status="Needs Review",
        method="category_rule",
        confidence=0.5,
    )
    return event
