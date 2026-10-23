"""图谱业务查询的测试。

重点不是"能查出东西"，而是**查不到时怎么说明**：缺坐标、未关联场馆、场馆没有活动，都必须以
missing 或 counts 的形式表达出来，而不是安静地返回空数组；客群一律标为假设。
"""
import json

import pytest

from backend import graph_query
from backend.database import connect, initialize


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "main.sqlite3"
    initialize(path)
    with connect(path) as con:
        con.execute("INSERT INTO sources VALUES(?,?,?,?,?,?)",
                    ("s1", "官方来源", "government", 0, "https://a.test", "2026-10-01T00:00:00+00:00"))
        con.execute("INSERT INTO districts(id,payload) VALUES(?,?)",
                    ("taicang", json.dumps({"id": "taicang", "name": "太仓市", "kind": "county_city"})))
        con.execute("INSERT INTO districts(id,payload) VALUES(?,?)",
                    ("gusu", json.dumps({"id": "gusu", "name": "姑苏区", "kind": "district"})))
        con.execute("INSERT INTO venues(id,payload) VALUES(?,?)", ("v1", json.dumps({
            "id": "v1", "name": "太仓大剧院", "districtId": "taicang",
            "coordinates": {"lng": 121.13, "lat": 31.46, "system": "GCJ-02", "status": "Verified",
                            "sourceUrl": "https://a.test"}})))
        con.execute("INSERT INTO venues(id,payload) VALUES(?,?)", ("v-no-coord", json.dumps({
            "id": "v-no-coord", "name": "无坐标场馆", "districtId": "taicang", "coordinates": None})))
        con.execute("INSERT INTO hotels(id,payload) VALUES(?,?)", ("h1", json.dumps({
            "id": "h1", "name": "陆渡宾馆", "districtId": "taicang",
            "coordinates": {"lng": 121.10, "lat": 31.45, "system": "GCJ-02", "status": "Verified",
                            "sourceUrl": "https://a.test"},
            "tierLabel": "中端"})))
        con.execute("INSERT INTO hotels(id,payload) VALUES(?,?)", ("h-no-coord", json.dumps({
            "id": "h-no-coord", "name": "无坐标酒店", "districtId": "taicang", "coordinates": None})))
    return path


def add_event(db, event_id, name, start, end=None, venue="v1", district="taicang", category="culture"):
    with connect(db) as con:
        con.execute(
            "INSERT INTO events(id,name,category,startDate,endDate,venue,district,source,"
            "verification_status,payload) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (event_id, name, category, start, end, venue, district, "s1", "Verified", "{}"),
        )


def test_venue_events_lists_upcoming_only(db):
    add_event(db, "e1", "未来活动", "2026-11-01")
    add_event(db, "e2", "过去活动", "2026-09-01")
    result = graph_query.venue_events(db, "v1", today="2026-10-24")
    assert result["ok"] is True
    assert [item["id"] for item in result["events"]] == ["e1"]
    assert result["events"][0]["relations"]["heldAt"] == "太仓大剧院"


def test_venue_events_reports_when_all_events_are_past(db):
    add_event(db, "e2", "过去活动", "2026-09-01")
    result = graph_query.venue_events(db, "v1", today="2026-10-24")
    assert result["events"] == []
    assert any("之前结束" in note for note in result["missing"])


def test_venue_events_flags_missing_coordinates(db):
    add_event(db, "e3", "无坐标场馆的活动", "2026-11-02", venue="v-no-coord")
    result = graph_query.venue_events(db, "v-no-coord", today="2026-10-24")
    assert any("坐标" in note for note in result["missing"])


def test_audience_is_marked_as_assumption(db):
    add_event(db, "e1", "活动", "2026-11-01", category="culture")
    result = graph_query.venue_events(db, "v1", today="2026-10-24")
    node = result["events"][0]
    assert node["audience"] == "文化/休闲客群"
    assert node["audienceIsAssumption"] is True
    assert any("规则推断" in note for note in result["assumptions"])


def test_hotel_nearby_excludes_events_without_coordinates_and_says_so(db):
    add_event(db, "near", "近处活动", "2026-11-01")
    add_event(db, "unknown", "无坐标活动", "2026-11-02", venue="v-no-coord")
    result = graph_query.hotel_nearby_events(db, "h1", today="2026-10-24")
    assert result["ok"] is True
    assert [item["id"] for item in result["events"]] == ["near"]
    assert result["counts"]["excludedNoCoordinates"] == 1
    assert any("缺少坐标" in note for note in result["missing"])


def test_hotel_nearby_rejects_hotel_without_coordinates(db):
    result = graph_query.hotel_nearby_events(db, "h-no-coord")
    assert result["ok"] is False
    assert "坐标" in result["reason"]


def test_hotel_nearby_respects_radius(db):
    add_event(db, "far", "很远的活动", "2026-11-01", district="gusu")
    with connect(db) as con:
        con.execute("UPDATE events SET venue='v1' WHERE id='far'")
    result = graph_query.hotel_nearby_events(db, "h1", radius_km=0.001, today="2026-10-24")
    assert result["events"] == []
    assert result["counts"]["excludedOutOfRadius"] == 1


def test_district_graph_counts_and_missing_relations(db):
    add_event(db, "e1", "有场馆活动", "2026-11-01")
    add_event(db, "e2", "无场馆活动", "2026-11-02", venue=None)
    result = graph_query.district_graph(db, "taicang")
    assert result["counts"]["events"] == 2
    assert result["counts"]["venues"] == 2
    assert result["counts"]["hotels"] == 2
    assert any("未关联场馆" in note for note in result["missing"])


def test_district_graph_reports_empty_district(db):
    result = graph_query.district_graph(db, "gusu")
    assert result["counts"]["events"] == 0
    assert any("暂无已关联场馆" in note for note in result["missing"])
    assert any("暂无已录入酒店" in note for note in result["missing"])


def test_unknown_ids_are_refused_with_a_reason(db):
    assert graph_query.venue_events(db, "nope")["ok"] is False
    assert graph_query.district_graph(db, "nope")["ok"] is False
