"""Places around a venue: the schema, the projection and the classification rule.

Two things are being pinned here. First, that a graph kind is only ever taken from the source's
own declared type — never from a name — and that station entrances, platforms, ticket halls,
heliports and sightseeing piers are dropped with that reason. Second, that ``places`` reaches the
frontend through the same additive path hotels do, so an existing database gains the table without
a migration and without touching anything already in it.
"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from backend.database import connect, initialize, snapshot
from backend.main import create_app
from crawler import places as places_module
from crawler.places import classify


def place_row(place_id="p-1", kind="restaurant", subtype="咖啡厅", lng=120.703, lat=31.321):
    return {
        "id": place_id,
        "kind": kind,
        "subtype": subtype,
        "name": "星巴克臻选(苏州科文中心店)",
        "address": "观枫街1号苏州科技文化艺术中心103商铺",
        "city": "苏州市",
        "district": "吴中区",
        "coordinates": {
            "lng": lng, "lat": lat, "system": "GCJ-02", "status": "Verified",
            "sourceUrl": "https://ditu.amap.com/place/B0FFG9VC8P",
        },
        "declaredType": "餐饮服务;咖啡厅;星巴克咖啡",
        "sampledNearVenueId": "venue-x",
        "sampledRadiusM": 1500,
        "distanceToVenueKm": 0.21,
    }


# --- classification: the source's own type decides -------------------------------

def test_restaurant_rows_keep_the_sources_middle_category():
    assert classify("餐饮服务;咖啡厅;星巴克咖啡") == ("restaurant", "咖啡厅")
    assert classify("餐饮服务;中餐厅;广东菜(粤菜)") == ("restaurant", "中餐厅")
    assert classify("餐饮服务;快餐厅;快餐厅") == ("restaurant", "快餐厅")
    assert classify("餐饮服务;外国餐厅;日本料理") == ("restaurant", "外国餐厅")
    # AMap's catch-all for food places it does not classify further is still a food place, and
    # the row keeps the source's own wording rather than being promoted to a specific cuisine.
    assert classify("餐饮服务;餐饮相关场所;餐饮相关") == ("restaurant", "餐饮相关场所")


def test_transport_rows_keep_the_station_and_drop_its_parts():
    assert classify("交通设施服务;地铁站;地铁站") == ("transport", "地铁站")
    assert classify("交通设施服务;公交车站;公交车站相关") == ("transport", "公交车站")
    assert classify("交通设施服务;火车站;火车站") == ("transport", "火车站")
    assert classify("交通设施服务;长途汽车站;长途汽车站") == ("transport", "长途汽车站")
    assert classify("交通设施服务;机场相关;飞机场") == ("transport", "机场")
    assert classify("交通设施服务;机场相关;机场相关") == ("transport", "机场")
    # A station's own parts are not the station: asking "how do I get here" must not answer
    # with a ticket hall or the third entrance.
    for declared in (
        "交通设施服务;地铁站;出入口",
        "交通设施服务;火车站;站台",
        "交通设施服务;火车站;售票",
        "交通设施服务;火车站;候车室",
        "交通设施服务;火车站;进站口/检票口",
        "交通设施服务;火车站;出站口",
    ):
        assert classify(declared) is None, declared


def test_categories_the_graph_does_not_draw_are_refused():
    for declared in (
        "交通设施服务;停车场;公共停车场",
        "交通设施服务;停车场;停车场入口",
        "交通设施服务;港口码头;港口码头",      # 金鸡湖的游船码头,不是到达方式
        "交通设施服务;机场相关;直升机场",      # 直升机不是旅客交通
        "交通设施服务;交通服务相关;交通服务相关",
        "住宿服务;宾馆酒店;五星级宾馆",        # hotels are their own resource
        "餐饮服务;休闲娱乐;棋牌室",            # dining root, but not a place to eat
        "",
        "餐饮服务",
        None,
    ):
        assert classify(declared) is None, declared


# --- the table is additive and the rows reach the API ---------------------------

def test_existing_database_gains_the_table_without_losing_anything(tmp_path):
    db = tmp_path / "places.sqlite3"
    initialize(db)
    with connect(db) as con:
        con.execute("INSERT INTO venues(id,payload) VALUES(?,?)",
                    ("venue-x", json.dumps({"id": "venue-x", "name": "苏州文化艺术中心"})))
        before = con.execute("SELECT COUNT(*) FROM venues").fetchone()[0]
    # A second initialize is what an upgraded deployment does on every start.
    initialize(db)
    with connect(db) as con:
        assert con.execute("SELECT COUNT(*) FROM venues").fetchone()[0] == before
        columns = {row[1] for row in con.execute("PRAGMA table_info(places)")}
        assert columns == {"id", "payload"}


def test_snapshot_and_the_places_endpoint_serve_the_rows(tmp_path):
    db = tmp_path / "places-api.sqlite3"
    initialize(db)
    with connect(db) as con:
        for row in (place_row(), place_row("p-2", "transport", "地铁站")):
            con.execute("INSERT OR REPLACE INTO places(id,payload) VALUES(?,?)",
                        (row["id"], json.dumps(row, ensure_ascii=False)))

    data = snapshot(db)
    assert [row["id"] for row in data["places"]] == ["p-1", "p-2"]
    assert [row["kind"] for row in data["places"]] == ["restaurant", "transport"]

    app = create_app(db)
    with TestClient(app) as client:
        assert client.get("/places").status_code == 200
        body = client.get("/dataset").json()
    assert [row["id"] for row in body["places"]] == ["p-1", "p-2"]
    # The dataset keeps one revision for every page, so the graph layer cannot be stale
    # relative to the events it is drawn around.
    assert body["status"]["eventCount"] == len(body["events"])


def test_a_place_keeps_where_it_was_sampled_from(tmp_path):
    """Coverage is a sample around venues, so the row must say which one and how far it reached."""
    db = tmp_path / "places-sample.sqlite3"
    initialize(db)
    row = place_row()
    with connect(db) as con:
        places_module.ensure_schema(con)
        con.execute("INSERT INTO places(id,payload) VALUES(?,?)",
                    (row["id"], json.dumps(row, ensure_ascii=False)))
    stored = snapshot(db)["places"][0]
    assert stored["sampledNearVenueId"] == "venue-x"
    assert stored["sampledRadiusM"] == 1500
    assert stored["coordinates"]["sourceUrl"].startswith("https://ditu.amap.com/place/")
