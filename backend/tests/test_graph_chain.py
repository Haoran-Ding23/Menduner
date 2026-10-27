"""图谱链路的测试（GPT Round 27 的三条验收）。

验收对应：
① 关系正确 —— 真实样例能还原场馆、223 米酒店、POI 距离；1682 米的中心不能被连成 800 米内关系
② 证据完整 —— recorded 边必须能解释来源；未核验关系显著标注，不伪装成已核验
③ 交互闭环（后端部分）—— 返回 actions 带 eventId，供前端跳地图
"""
import json

import pytest

from backend import graph_chain
from backend.database import connect, initialize


def add(con, table, ident, payload):
    con.execute(f"INSERT INTO {table}(id,payload) VALUES(?,?)", (ident, json.dumps(payload, ensure_ascii=False)))


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "main.sqlite3"
    initialize(path)
    with connect(path) as con:
        con.execute("INSERT INTO sources VALUES(?,?,?,?,?,?)",
                    ("src1", "苏州市人民政府公开活动报道", "government", 0,
                     "https://a.test/report", "2026-10-01T00:00:00+00:00"))
        add(con, "venues", "venue-li", {"id": "venue-li", "name": "李公堤文化创意街区",
                                        "coordinates": {"lng": 120.68223, "lat": 31.302961,
                                                        "system": "GCJ-02", "status": "Verified",
                                                        "sourceUrl": "https://ditu.amap.com/place/B0FFGFUS26"}})
        add(con, "hotels", "hotel-near", {"id": "hotel-near", "name": "美锦·沃姆酒店",
                                          "coordinates": {"lng": 120.68300, "lat": 31.30300,
                                                          "system": "GCJ-02", "status": "Verified",
                                                          "sourceUrl": "https://a.test/h1"}})
        add(con, "hotels", "hotel-far", {"id": "hotel-far", "name": "远处酒店",
                                         "coordinates": {"lng": 120.7000, "lat": 31.3200,
                                                         "system": "GCJ-02", "status": "Verified"}})
        add(con, "hotels", "hotel-nocoord", {"id": "hotel-nocoord", "name": "无坐标酒店"})
        add(con, "places", "poi-dining", {"id": "poi-dining", "name": "锦作·蟹粉黄鱼火锅(李公堤店)",
                                          "type": "dining",
                                          "coordinates": {"lng": 120.68285, "lat": 31.30299,
                                                          "system": "GCJ-02", "status": "Verified"}})
        add(con, "places", "poi-bus", {"id": "poi-bus", "name": "李公堤(公交站)", "type": "transport",
                                       "coordinates": {"lng": 120.68320, "lat": 31.30300,
                                                       "system": "GCJ-02", "status": "Verified"}})
        # 候选中心：1682 米外，超出 800 米半径
        add(con, "districts", "area-far", {"id": "area-far", "name": "星悦汇周边", "kind": "business_area",
                                           "status": "candidate",
                                           "center": {"lng": 120.6970, "lat": 31.3110, "system": "GCJ-02",
                                                      "radiusMeters": 800, "matchLevel": "candidate"}})
        con.execute(
            "INSERT INTO events(id,name,category,startDate,endDate,venue,district,source,"
            "verification_status,payload) VALUES(?,?,?,?,?,?,?,?,?,?)",
            ("evt-real", "2026第五届苏州金鸡湖中法文化艺术周", "culture", "2026-11-01", "2026-11-03",
             "venue-li", None, "src1", "Needs Review", "{}"),
        )
    return path


def test_recorded_edge_is_not_verified(db):
    chain = graph_chain.event_chain(db, "evt-real")
    held = next(edge for edge in chain["edges"] if edge["type"] == "HELD_AT")
    assert held["kind"] == "recorded"
    # 活动状态是 Needs Review，边不能显示成 Verified
    assert held["verificationStatus"] == "Needs Review"
    assert held["evidenceRefs"][0]["field"] == "venue"
    assert any("尚未核验" in warning for warning in chain["warnings"])


def test_nearby_hotel_and_poi_with_calculation(db):
    chain = graph_chain.event_chain(db, "evt-real", radius_meters=800)
    hotels = {item["id"]: item for item in chain["nearbyHotels"]}
    assert "hotel-near" in hotels and "hotel-far" not in hotels
    assert hotels["hotel-near"]["distanceMeters"] < 300
    edge = next(e for e in chain["edges"] if e["toId"] == "hotel-near")
    assert edge["kind"] == "computed"
    assert edge["calculation"]["method"] == "haversine-v1"
    assert edge["calculation"]["coordinateSystem"] == "GCJ-02"
    assert edge["calculation"]["radiusMeters"] == 800
    assert edge["calculation"]["calculatedAt"]
    places = {item["id"]: item for item in chain["nearbyPlaces"]}
    assert places["poi-dining"]["category"] == "dining"
    assert places["poi-bus"]["category"] == "transport"


def test_area_center_outside_radius_is_not_connected(db):
    chain = graph_chain.event_chain(db, "evt-real", radius_meters=800)
    center = chain["nearbyAreaCenter"]
    assert center["insideRadius"] is False
    assert not any(edge["type"] == "WITHIN_RADIUS" for edge in chain["edges"])
    assert any("超出半径" in warning for warning in chain["warnings"])


def test_missing_relations_are_explained_not_invented(db):
    chain = graph_chain.event_chain(db, "evt-real")
    # 无坐标实体不得出现在距离关系里
    assert not any(node["id"] == "hotel-nocoord" for node in chain["nodes"])
    # 节点数必须与边覆盖一致：孤立的 POI/酒店不允许凭空连边
    for edge in chain["edges"]:
        if edge["kind"] == "computed":
            assert edge["calculation"]["distanceMeters"] <= edge["calculation"]["radiusMeters"]


def test_actions_carry_event_id_for_map_jump(db):
    chain = graph_chain.event_chain(db, "evt-real")
    map_action = next(item for item in chain["actions"] if item["type"] == "open_map")
    assert map_action["eventId"] == "evt-real"


def test_canonical_dedupe_and_date_conflict(db):
    with connect(db) as con:
        try:
            con.execute("ALTER TABLE events ADD COLUMN canonical_id TEXT")
        except Exception:
            pass
        con.execute(
            "INSERT INTO events(id,name,category,startDate,endDate,venue,district,source,"
            "verification_status,payload,canonical_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            ("evt-dup", "同一活动另一来源", "culture", "2026-11-02", "2026-11-04",
             "venue-li", None, "src1", "Needs Review", "{}", "evt-real"),
        )
    chain = graph_chain.event_chain(db, "evt-real")
    assert any("起止日期不一致" in warning for warning in chain["warnings"])
    assert any("canonical_id 去重" in warning for warning in chain["warnings"])
    event_node = next(node for node in chain["nodes"] if node["type"] == "Event")
    assert set(event_node["attributes"]["recordIds"]) == {"evt-real", "evt-dup"}
