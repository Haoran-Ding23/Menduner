"""工作台数据层的测试：快照比较与跟进状态。

重点是三件容易被做错的事：
  * 只有一份快照时必须说「尚无可比较记录」，不能报「没有变化」；
  * 改期与新增、取消要分开，因为对酒店的意义不同；
  * 跟进状态按租户隔离，A 酒店不能看到或改动 B 酒店的状态。
"""
import json

import pytest

from backend import tracking
from backend.database import connect, initialize


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "main.sqlite3"
    initialize(path)
    with connect(path) as con:
        con.execute("INSERT INTO sources VALUES(?,?,?,?,?,?)",
                    ("s1", "来源", "government", 0, "https://a.test", "2026-10-01T00:00:00+00:00"))
        con.execute("INSERT INTO districts(id,payload) VALUES(?,?)",
                    ("suzhou", json.dumps({"id": "suzhou", "name": "苏州市", "kind": "city"})))
    with connect(path) as con:
        try:
            con.execute("ALTER TABLE events ADD COLUMN canonical_id TEXT")
        except Exception:
            pass
    return path


def add_event(db, event_id, name, start, end=None, canonical=None):
    with connect(db) as con:
        con.execute(
            "INSERT INTO events(id,name,category,startDate,endDate,venue,district,source,"
            "verification_status,payload,canonical_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (event_id, name, "culture", start, end, None, "suzhou", "s1", "Needs Review",
             "{}", canonical or event_id),
        )


def remove_event(db, event_id):
    with connect(db) as con:
        con.execute("DELETE FROM events WHERE id=?", (event_id,))


def rename_event(db, event_id, name):
    with connect(db) as con:
        con.execute("UPDATE events SET name=? WHERE id=?", (name, event_id))


def test_capture_is_idempotent(db):
    add_event(db, "e1", "活动一", "2026-10-24")
    first = tracking.capture(db, "2026-10-23")
    second = tracking.capture(db, "2026-10-23")
    assert first["events"] == second["events"] == 1
    assert tracking.snapshot_dates(db) == ["2026-10-23"]


def test_capture_uses_canonical_identity(db):
    """同一活动的两条来源记录只产生一行快照，与统计口径一致。"""
    add_event(db, "canon", "同一活动", "2026-10-24", canonical="canon")
    add_event(db, "dup", "同一活动", "2026-10-24", canonical="canon")
    tracking.capture(db, "2026-10-23")
    with connect(db) as con:
        rows = list(con.execute("SELECT event_key FROM event_snapshots"))
    assert [row["event_key"] for row in rows] == ["canon"]


def test_single_snapshot_is_not_comparable(db):
    add_event(db, "e1", "活动一", "2026-10-24")
    tracking.capture(db, "2026-10-23")
    result = tracking.changes(db)
    assert result["comparable"] is False
    assert "尚无可比较记录" in result["reason"]


def test_no_snapshot_at_all_is_reported_as_such(db):
    result = tracking.changes(db)
    assert result["comparable"] is False
    assert result["reason"] == "尚无快照记录"


def test_detects_added_cancelled_and_rescheduled(db):
    add_event(db, "stay", "保留的活动", "2026-10-24")
    add_event(db, "move", "改期的活动", "2026-10-25")
    add_event(db, "gone", "取消的活动", "2026-10-26")
    tracking.capture(db, "2026-10-23")

    add_event(db, "fresh", "新出现的活动", "2026-11-01")
    remove_event(db, "gone")
    with connect(db) as con:
        con.execute("UPDATE events SET startDate='2026-10-28' WHERE id='move'")
    tracking.capture(db, "2026-10-24")

    result = tracking.changes(db)
    assert result["comparable"] is True
    assert [e["event_key"] for e in result["added"]] == ["fresh"]
    assert [e["event_key"] for e in result["cancelled"]] == ["gone"]
    assert [e["before"]["event_key"] for e in result["rescheduled"]] == ["move"]
    assert result["changed"] == []


def test_detects_name_change_separately_from_reschedule(db):
    add_event(db, "e1", "旧名称", "2026-10-24")
    tracking.capture(db, "2026-10-23")
    rename_event(db, "e1", "新名称")
    tracking.capture(db, "2026-10-24")
    result = tracking.changes(db)
    assert result["rescheduled"] == []
    assert [e["after"]["name"] for e in result["changed"]] == ["新名称"]


def test_followups_are_scoped_per_tenant(db):
    tracking.set_followup(db, tenant_id="hotel-a", event_key="e1", state="watching",
                          note="值得跟进", actor="manager01")
    tracking.set_followup(db, tenant_id="hotel-b", event_key="e1", state="ignored",
                          actor="manager02")

    a = tracking.list_followups(db, "hotel-a")
    b = tracking.list_followups(db, "hotel-b")
    assert [row["state"] for row in a] == ["watching"]
    assert [row["state"] for row in b] == ["ignored"]
    assert a[0]["stateLabel"] == "关注"


def test_set_followup_overwrites_state(db):
    tracking.set_followup(db, tenant_id="hotel-a", event_key="e1", state="todo")
    tracking.set_followup(db, tenant_id="hotel-a", event_key="e1", state="done", note="已联系主办方")
    rows = tracking.list_followups(db, "hotel-a")
    assert len(rows) == 1
    assert rows[0]["state"] == "done"
    assert rows[0]["note"] == "已联系主办方"


def test_rejects_unknown_state(db):
    with pytest.raises(ValueError, match="状态必须是"):
        tracking.set_followup(db, tenant_id="hotel-a", event_key="e1", state="maybe")


def test_clear_followup_is_scoped(db):
    tracking.set_followup(db, tenant_id="hotel-a", event_key="e1", state="watching")
    assert tracking.clear_followup(db, tenant_id="hotel-b", event_key="e1") is False
    assert tracking.clear_followup(db, tenant_id="hotel-a", event_key="e1") is True
    assert tracking.list_followups(db, "hotel-a") == []
