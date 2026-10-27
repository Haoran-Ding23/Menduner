"""人工补录的测试：必须有来源、字段受限、留痕、不产生重复行。"""
import json

import pytest

from backend import manual_fill
from backend.database import connect, initialize


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "main.sqlite3"
    initialize(path)
    with connect(path) as con:
        con.execute("INSERT INTO sources VALUES(?,?,?,?,?,?)",
                    ("s1", "来源", "government", 0, "https://a.test", "2026-10-01T00:00:00+00:00"))
        con.execute(
            "INSERT INTO events(id,name,category,startDate,endDate,venue,district,source,"
            "verification_status,payload) VALUES(?,?,?,?,?,?,?,?,?,?)",
            ("e1", "活动一", "culture", "2026-11-01", None, None, None, "s1", "Needs Review", "{}"))
        con.execute(
            "INSERT INTO evidence(id,event_id,entity_id,field,value,source_url,verification_status,payload) "
            "VALUES(?,?,?,?,?,?,?,?)",
            ("ev1", "e1", "e1", "organizer", None, None, "Missing", "{}"))
    return path


def test_fill_requires_source_url(db):
    with pytest.raises(manual_fill.FillError):
        manual_fill.fill(db, event_id="e1", field="organizer", value="某主办方",
                         source_url="", reviewer="manager01")


def test_fill_rejects_unknown_field(db):
    with pytest.raises(manual_fill.FillError):
        manual_fill.fill(db, event_id="e1", field="secretField", value="x",
                         source_url="https://a.test", reviewer="manager01")


def test_fill_rejects_empty_value(db):
    with pytest.raises(manual_fill.FillError):
        manual_fill.fill(db, event_id="e1", field="organizer", value="   ",
                         source_url="https://a.test", reviewer="manager01")


def test_fill_updates_existing_row_and_keeps_history_note(db):
    result = manual_fill.fill(db, event_id="e1", field="organizer", value="苏州文化中心",
                              source_url="https://a.test/x", reviewer="manager01", note="官方公告")
    assert result["action"] == "updated"
    with connect(db) as con:
        row = con.execute("SELECT value, source_url, verification_status, payload FROM evidence WHERE id='ev1'").fetchone()
        count = con.execute("SELECT COUNT(*) FROM evidence WHERE field='organizer'").fetchone()[0]
    assert row["value"] == "苏州文化中心"
    assert row["source_url"] == "https://a.test/x"
    assert row["verification_status"] == "Verified"
    payload = json.loads(row["payload"])
    assert payload["method"] == "manual_entry"
    assert payload["providedBy"] == "manager01"
    assert "覆盖原状态 Missing" in payload["note"]
    assert count == 1, "同一字段不应出现重复证据行"


def test_fill_creates_row_when_absent(db):
    result = manual_fill.fill(db, event_id="e1", field="endDate", value="2026-11-05",
                              source_url="https://a.test/y", reviewer="manager01")
    assert result["action"] == "created"
    with connect(db) as con:
        row = con.execute("SELECT value, verification_status FROM evidence WHERE event_id='e1' AND field='endDate'").fetchone()
        event_end = con.execute("SELECT endDate FROM events WHERE id='e1'").fetchone()[0]
    assert row["value"] == "2026-11-05"
    assert row["verification_status"] == "Verified"
    assert event_end == "2026-11-05", "补录的日期要落到活动表，否则页面仍显示旧值"


def test_fill_unknown_event_raises_keyerror(db):
    with pytest.raises(KeyError):
        manual_fill.fill(db, event_id="nope", field="organizer", value="x",
                         source_url="https://a.test", reviewer="manager01")


def test_fill_rejects_bad_date(db):
    with pytest.raises(manual_fill.FillError):
        manual_fill.fill(db, event_id="e1", field="endDate", value="苏州交响乐团",
                         source_url="https://a.test", reviewer="manager01")
