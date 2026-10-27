"""关系状态随字段核对更新（12 轮第 11 轮闭环）。"""
import json

from backend import graph_chain
from backend.database import connect, initialize


def add(con, table, ident, payload):
    con.execute(f"INSERT INTO {table}(id,payload) VALUES(?,?)", (ident, json.dumps(payload, ensure_ascii=False)))


def build(tmp_path):
    path = tmp_path / "main.sqlite3"
    initialize(path)
    with connect(path) as con:
        con.execute("INSERT INTO sources VALUES(?,?,?,?,?,?)",
                    ("s1", "来源", "government", 0, "https://a.test", "2026-10-01T00:00:00+00:00"))
        add(con, "venues", "v1", {"id": "v1", "name": "场馆",
                                  "coordinates": {"lng": 120.62, "lat": 31.31, "system": "GCJ-02",
                                                  "status": "Verified"}})
        con.execute(
            "INSERT INTO events(id,name,category,startDate,endDate,venue,district,source,"
            "verification_status,payload) VALUES(?,?,?,?,?,?,?,?,?,?)",
            ("e1", "活动", "culture", "2026-11-01", "2026-11-03", "v1", None, "s1",
             "Needs Review", "{}"))
        con.execute(
            "INSERT INTO evidence(id,event_id,entity_id,field,value,source_url,verification_status,payload) "
            "VALUES(?,?,?,?,?,?,?,?)",
            ("ev1", "e1", "e1", "venueName", "场馆", "https://a.test", "Needs Review", "{}"))
    return path


def test_edge_status_changes_after_field_review(tmp_path):
    path = build(tmp_path)
    before = graph_chain.event_chain(path, "e1")
    held_before = next(e for e in before["edges"] if e["type"] == "HELD_AT")
    assert held_before["verificationStatus"] == "Needs Review"
    assert any("尚未核验" in w for w in before["warnings"])

    with connect(path) as con:
        con.execute("UPDATE evidence SET verification_status='Verified' WHERE id='ev1'")

    after = graph_chain.event_chain(path, "e1")
    held_after = next(e for e in after["edges"] if e["type"] == "HELD_AT")
    assert held_after["verificationStatus"] == "Verified"
    assert not any("尚未核验" in w for w in after["warnings"])


def test_conflicting_field_keeps_edge_conflicting(tmp_path):
    path = build(tmp_path)
    with connect(path) as con:
        con.execute("UPDATE evidence SET verification_status='Conflicting' WHERE id='ev1'")
    chain = graph_chain.event_chain(path, "e1")
    held = next(e for e in chain["edges"] if e["type"] == "HELD_AT")
    # 图谱协议只有三种状态：来源冲突按「待核实」呈现，不冒充已核验
    assert held["verificationStatus"] == "Needs Review"
    assert held["evidenceRefs"], "冲突也必须保留证据引用，便于人工判断"


def test_no_field_evidence_falls_back_to_event_status(tmp_path):
    path = build(tmp_path)
    with connect(path) as con:
        con.execute("DELETE FROM evidence")
    chain = graph_chain.event_chain(path, "e1")
    held = next(e for e in chain["edges"] if e["type"] == "HELD_AT")
    # 没有字段证据时退回活动整体状态（Needs Review），不能凭空变成 Verified
    assert held["verificationStatus"] == "Needs Review"
