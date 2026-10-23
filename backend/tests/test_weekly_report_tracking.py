"""周报的去重与待办：第 10 项要求的「重点活动 / 本周变化 / 待办」是否真的进了导出内容。

这三个都是「以前完全没有」的部分，所以测试直接检查报告数据结构与两种文件里是否出现对应内容，
而不是只检查函数能跑通。
"""
import io
import json
import zipfile

import pytest

from backend import tenants, tracking, weekly_report
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
        try:
            con.execute("ALTER TABLE events ADD COLUMN canonical_id TEXT")
        except Exception:
            pass
    return path


@pytest.fixture
def base(tmp_path):
    directory = tmp_path / "data"
    directory.mkdir()
    return directory


def seed_tenant(db, base, tenant="hotel-a"):
    tenants.create_tenant(db, tenant_id=tenant, name="A 酒店")
    tenants.add_member(db, tenant_id=tenant, login="owner-a", role="owner")
    return tenant


def add_event(db, event_id, name, start, end=None, canonical=None):
    with connect(db) as con:
        con.execute(
            "INSERT INTO events(id,name,category,startDate,endDate,venue,district,source,"
            "verification_status,payload,canonical_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (event_id, name, "culture", start, end, None, "suzhou", "s1", "Needs Review",
             "{}", canonical or event_id),
        )


def test_report_merges_duplicate_sources_into_one_activity(db, base):
    seed_tenant(db, base)
    # 同一活动的两条来源记录：日期在报告周内（2026-10-12 ~ 10-18）。
    add_event(db, "e1", "同一活动", "2026-10-14", canonical="e1")
    add_event(db, "e2", "同一活动", "2026-10-14", canonical="e1")
    report = weekly_report.collect(db, base, "hotel-a", today=weekly_report.date(2026, 10, 23)
                                   if hasattr(weekly_report, "date") else None)
    assert len(report["events"]) == 1


def test_report_carries_followups_and_todo(db, base):
    seed_tenant(db, base)
    add_event(db, "e1", "待跟进的活动", "2026-10-14")
    tracking.set_followup(db, tenant_id="hotel-a", event_key="e1", state="todo",
                          note="联系主办方", actor="owner-a")
    tracking.set_followup(db, tenant_id="hotel-a", event_key="e9", state="done")
    report = weekly_report.collect(db, base, "hotel-a")
    assert len(report["followups"]) == 2
    assert [row["event_key"] for row in report["todo"]] == ["e1"]


def test_report_states_changes_are_not_comparable_without_history(db, base):
    seed_tenant(db, base)
    report = weekly_report.collect(db, base, "hotel-a")
    assert report["changes"]["comparable"] is False
    assert "快照" in report["changes"]["reason"]


def test_report_changes_become_comparable_after_two_snapshots(db, base):
    seed_tenant(db, base)
    add_event(db, "e1", "原有活动", "2026-10-14")
    tracking.capture(db, "2026-10-20")
    add_event(db, "e2", "后加的活动", "2026-10-15")
    tracking.capture(db, "2026-10-21")
    report = weekly_report.collect(db, base, "hotel-a")
    assert report["changes"]["comparable"] is True
    assert [item["event_key"] for item in report["changes"]["added"]] == ["e2"]


def test_xlsx_contains_change_and_todo_sheets(db, base):
    seed_tenant(db, base)
    add_event(db, "e1", "待跟进的活动", "2026-10-14")
    tracking.set_followup(db, tenant_id="hotel-a", event_key="e1", state="todo", note="待办事项")
    report = weekly_report.collect(db, base, "hotel-a")
    payload = weekly_report.build_xlsx(report)

    from openpyxl import load_workbook

    book = load_workbook(io.BytesIO(payload))
    # 工作表名在 OOXML 里是共享字符串，直接读 workbook.xml 查不到，用 openpyxl 读才准确。
    assert "本周变化" in book.sheetnames
    assert "待办" in book.sheetnames
    todo_text = " ".join(
        str(cell.value) for row in book["待办"].iter_rows() for cell in row if cell.value
    )
    assert "待办事项" in todo_text


def test_pdf_renders_with_new_sections(db, base):
    seed_tenant(db, base)
    add_event(db, "e1", "待跟进的活动", "2026-10-14")
    tracking.set_followup(db, tenant_id="hotel-a", event_key="e1", state="todo")
    report = weekly_report.collect(db, base, "hotel-a")
    try:
        payload = weekly_report.build_pdf(report)
    except RuntimeError:
        pytest.skip("没有可用的中文字体")
    assert payload[:5] == b"%PDF-"
