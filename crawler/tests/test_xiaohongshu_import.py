"""Offline Xiaohongshu note-import checks. Synthetic MediaCrawler rows, a fake AI reader.

These tests pin the social-note clue pool's fail-closed contract:

* a note's **publish timestamp is provenance only** and can never become an event date —
  the same rule that keeps bureau news columns and library archives out of the event
  tables;
* the deterministic pre-screen demands an explicit Suzhou place signal and a
  year-bearing date before a single AI token is spent; anything else is retained as
  Context with the reason recorded;
* the AI reading contributes a field only with its verbatim quote, and only when the
  reading itself carries a year-bearing start date;
* the source has no registry trust level, so every published field is Needs Review —
  nothing from a social note is ever auto-Verified;
* re-importing the same note keeps one event: the observation for
  ``(source_id, item_key)`` is replaced, the human-review history survives.
"""
import json
from pathlib import Path

import pytest

from backend.database import connect
from crawler.ai.enrich import read_page
from crawler.pipeline import run_pipeline
from crawler.sources.community.xiaohongshu import (
    XiaohongshuImportAdapter,
    load_notes,
    note_date,
    prescreen,
    social_note_ai,
)

SOURCE_ID = XiaohongshuImportAdapter.source_id

PUBLISH_TS = 1730000000000  # 2024-10-27, deliberately far from the stated event dates


def note_row(**overrides):
    row = {
        "note_id": "note-001",
        "type": "note",
        "title": "苏州博物馆特展预告",
        "desc": (
            "苏州博物馆本馆特展「吴门四家」下周开展！\n"
            "时间：2026年11月1日 - 2026年12月1日\n"
            "地点：苏州博物馆（姑苏区东北街204号）\n"
            "本次展览汇集文徵明、唐寅等吴门画派真迹三十余件，"
            "需要在公众号提前预约，免费入场，周一闭馆记得别跑空。"
        ),
        "time": PUBLISH_TS,
        "nickname": "小铃",
        "liked_count": "12",
        "source_keyword": "苏州 展览",
        "tag_list": "苏州,展览",
        "note_url": "https://www.xiaohongshu.com/explore/note-001?xsec_token=abc",
    }
    row.update(overrides)
    return row


class FakeAI:
    """Returns one canned enrichment document, recording the prompts it was asked."""

    def __init__(self, document):
        self.document = document
        self.prompts = []

    def complete_json(self, **kwargs):
        self.prompts.append(kwargs)
        return self.document


def reading_doc(**overrides):
    document = {
        "is_event": True,
        "certainty": "high",
        "event_name": {"value": "苏州博物馆特展", "evidence": "苏州博物馆特展预告"},
        "start_date": {"value": "2026-11-01", "evidence": "时间：2026年11月1日"},
        "end_date": {"value": "2026-12-01", "evidence": "2026年12月1日"},
        "venue": {"value": "苏州博物馆", "evidence": "地点：苏州博物馆"},
        "location": None,
        "organizer": None,
    }
    document.update(overrides)
    return document


def run_import(tmp_path, rows, document=None, ai=True):
    db = tmp_path / "import.sqlite3"
    reader = FakeAI(document) if ai else None
    adapter = XiaohongshuImportAdapter(notes=rows, ai_client=reader)
    report = run_pipeline(db, [adapter])
    return db, report, adapter


def raw_rows(db):
    with connect(db) as con:
        return con.execute("SELECT * FROM crawler_raw_items").fetchall()


# --- pre-screen -------------------------------------------------------------------

@pytest.mark.parametrize(
    "text,expected",
    [
        ("姑苏区有展 时间2026-11-01", True),
        ("昆山 drone show 2026年11月1日", True),
        ("常熟 2026.11.1 集市", True),
        ("苏州 展览", False),  # no date
        ("11月1日开展", False),  # no Suzhou signal
        ("上海 大展 2026-11-01", False),  # another city
        ("北京高新区 2026-11-01", False),  # generic 高新区 is not a Suzhou signal
        ("明天苏州有活动", False),  # relative date, no year
    ],
)
def test_prescreen_demands_suzhou_signal_and_year_date(text, expected):
    assert prescreen(text)[0] is expected


def test_note_date_accepts_prompt_forms_and_rejects_yearless():
    assert note_date("2026-11-01") == "2026-11-01"
    assert note_date("2026年11月1日") == "2026-11-01"
    assert note_date("2026.11.01") == "2026-11-01"
    assert note_date("11月1日") is None
    assert note_date(None) is None


# --- end-to-end through the pipeline ----------------------------------------------

def test_passing_note_publishes_pending_event(tmp_path):
    db, report, adapter = run_import(tmp_path, [note_row()], reading_doc())
    attempt = report["attempts"][0]
    assert attempt["source"] == SOURCE_ID
    assert attempt["accepted"] == 1
    assert adapter.investigation["prescreenPassed"] == 1
    assert adapter.investigation["aiReadings"] == 1

    with connect(db) as con:
        event = con.execute("SELECT * FROM events").fetchone()
        assert event["startDate"] == "2026-11-01"
        assert event["endDate"] == "2026-12-01"
        # The events.venue column holds the venue reference id; the name the note used
        # stays on the payload, and the alias table binds 苏州博物馆 to its canonical row.
        payload = json.loads(event["payload"])
        assert payload["venueName"] == "苏州博物馆"
        assert payload["venueId"]
        assert event["source"] == SOURCE_ID
        # The whole point of the review queue: nothing from a social note is Verified.
        assert event["verification_status"] != "Verified"

        claim = con.execute(
            "SELECT * FROM crawler_evidence WHERE event_id=? AND field_name='start_date'",
            (event["id"],),
        ).fetchone()
        assert claim["verification_status"] == "Needs Review"
        assert claim["value"] == '"2026-11-01"'
        payload = json.loads(
            con.execute(
                "SELECT payload FROM evidence WHERE id=?", (claim["id"],)
            ).fetchone()["payload"]
        )
        assert payload["method"] == "ai_note_extraction"
        assert payload["snippet"] == "时间：2026年11月1日"
        assert payload["confidence"] <= 0.7


def test_publish_timestamp_never_becomes_the_event_date(tmp_path):
    db, _, _ = run_import(tmp_path, [note_row()], reading_doc())
    with connect(db) as con:
        event = con.execute("SELECT startDate FROM events").fetchone()
    from datetime import datetime, timezone

    publish_day = datetime.fromtimestamp(PUBLISH_TS / 1000, tz=timezone.utc).date().isoformat()
    assert event["startDate"] != publish_day
    assert event["startDate"] == "2026-11-01"


def test_publish_time_is_stored_as_metadata_only(tmp_path):
    db, _, _ = run_import(tmp_path, [note_row()], reading_doc())
    with connect(db) as con:
        payload = con.execute("SELECT payload FROM events").fetchone()["payload"]
    assert str(PUBLISH_TS) not in payload


def test_non_suzhou_note_is_retained_as_context_without_ai_spend(tmp_path):
    db, report, adapter = run_import(
        tmp_path, [note_row(title="随手拍", desc="今天天气不错 2026-11-01", tag_list="")], reading_doc()
    )
    assert adapter.investigation["prescreenContext"] == 1
    assert adapter.investigation["aiReadings"] == 0
    assert report["attempts"][0]["accepted"] == 0
    (raw,) = raw_rows(db)
    assert raw["validation_status"] == "Context"
    with connect(db) as con:
        assert con.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0


def test_passing_note_without_ai_client_is_rejected_with_reason(tmp_path):
    db, report, _ = run_import(tmp_path, [note_row()], ai=False)
    assert report["attempts"][0]["rejected"] == 1
    (raw,) = raw_rows(db)
    assert raw["validation_status"] == "Rejected"
    assert "No AI reading" in raw["error"]


def test_ai_judges_note_not_an_event(tmp_path):
    db, report, _ = run_import(
        tmp_path, [note_row()], reading_doc(is_event=False, event_name=None)
    )
    assert report["attempts"][0]["accepted"] == 0
    (raw,) = raw_rows(db)
    assert raw["validation_status"] == "Rejected"
    assert "not a concrete event" in raw["error"]


def test_month_day_without_year_is_rejected_not_repaired(tmp_path):
    document = reading_doc(start_date={"value": "11月1日", "evidence": "11月1日开幕"})
    db, report, _ = run_import(tmp_path, [note_row()], document)
    assert report["attempts"][0]["accepted"] == 0
    (raw,) = raw_rows(db)
    assert raw["validation_status"] == "Rejected"
    assert "year-bearing start date" in raw["error"]


def test_out_of_town_place_fails_closed(tmp_path):
    document = reading_doc(venue={"value": "上海博物馆", "evidence": "地点：上海博物馆"})
    db, report, _ = run_import(tmp_path, [note_row()], document)
    assert report["attempts"][0]["accepted"] == 0
    (raw,) = raw_rows(db)
    assert "not explicitly in Suzhou" in raw["error"]


def test_claim_without_verbatim_quote_is_dropped(tmp_path):
    # read_page discards any value whose quote is missing, so the reading arrives
    # without a name and the note is rejected instead of published unsupported.
    document = reading_doc(event_name={"value": "某展", "evidence": ""})
    reader = FakeAI(document)
    row = note_row()
    reading = read_page(reader, url=row["note_url"], html=f'{row["title"]}\n{row["desc"]}')
    assert reading.is_event is True
    assert not reading.fields["event_name"].present
    db, report, _ = run_import(tmp_path, [row], document)
    assert report["attempts"][0]["accepted"] == 0
    (raw,) = raw_rows(db)
    assert "year-bearing start date" in raw["error"] or "explicit event name" in raw["error"]


def test_ai_prompt_carries_the_note_body(tmp_path):
    reader = FakeAI(reading_doc())
    adapter = XiaohongshuImportAdapter(notes=[note_row()], ai_client=reader)
    items = adapter.collect()
    assert len(items) == 1
    assert len(reader.prompts) == 1
    assert "苏州博物馆特展预告" in reader.prompts[0]["user"]
    assert items[0].request_metadata["ai_reading"]["is_event"] is True


def test_reimport_reuses_the_same_event(tmp_path):
    db, _, _ = run_import(tmp_path, [note_row()], reading_doc())
    with connect(db) as con:
        first_event = con.execute("SELECT id FROM events").fetchone()["id"]
    db2, report2, _ = run_import(tmp_path, [note_row()], reading_doc(certainty="medium"))
    assert report2["attempts"][0]["accepted"] == 1
    with connect(db2) as con:
        events = con.execute("SELECT id FROM events").fetchall()
        observations = con.execute(
            "SELECT * FROM crawler_observations WHERE source_id=?", (SOURCE_ID,)
        ).fetchall()
    assert [row["id"] for row in events] == [first_event]
    assert len(observations) == 1


# --- export loading ---------------------------------------------------------------

def test_jsonl_export_dedupes_by_note_id(tmp_path):
    export = tmp_path / "xhs_note.jsonl"
    rows = [note_row(), note_row(liked_count="99"), note_row(note_id="note-002", title="无关")]
    export.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8"
    )
    loaded = load_notes(export)
    assert [row["note_id"] for row in loaded] == ["note-001", "note-002"]
    assert loaded[0]["liked_count"] == "12"  # first occurrence wins


def test_unsupported_export_format_is_refused(tmp_path):
    with pytest.raises(ValueError, match="Unsupported MediaCrawler export format"):
        load_notes(tmp_path / "notes.xlsx")
