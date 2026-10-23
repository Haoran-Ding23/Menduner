"""Neo4j 同步的图构建测试（不需要跑 Neo4j）。

同步脚本的价值全在「从数据库读出来的边是否只画数据里写着的东西」，所以测的是 build_graph，
不是驱动。
"""
import json

import pytest

from backend import graph_sync
from backend.database import connect, initialize


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "main.sqlite3"
    initialize(path)
    with connect(path) as con:
        con.execute("INSERT INTO sources VALUES(?,?,?,?,?,?)",
                    ("s1", "src", "government", 0, "https://example.test", "2026-10-23T00:00:00+00:00"))
        con.execute("INSERT INTO districts(id,payload) VALUES(?,?)",
                    ("taicang", json.dumps({"id": "taicang", "name": "太仓市", "kind": "county_city"})))
        con.execute("INSERT INTO venues(id,payload) VALUES(?,?)",
                    ("v1", json.dumps({"id": "v1", "name": "太仓大剧院", "districtId": "taicang",
                                       "coordinates": {"status": "Verified", "lng": 1, "lat": 2}})))
        con.execute("INSERT INTO venues(id,payload) VALUES(?,?)",
                    ("v2", json.dumps({"id": "v2", "name": "无坐标场馆", "districtId": None,
                                       "coordinates": None})))
        con.execute("INSERT INTO hotels(id,payload) VALUES(?,?)",
                    ("h1", json.dumps({"id": "h1", "name": "某酒店", "districtId": "taicang",
                                       "officialStar": {"level": 5}})))
        con.execute(
            "INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?)",
            ("e1", "德云社太仓站", "culture", "2026-01-11", None, "v1", "taicang", "s1",
             "Needs Review", "{}"),
        )
        con.execute(
            "INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?)",
            ("e2", "没有场馆的活动", "culture", "2026-03-01", None, None, None, "s1",
             "Needs Review", "{}"),
        )
    return path


def test_nodes_follow_the_tables(db):
    graph = graph_sync.build_graph(db)
    assert len(graph["nodes"]["District"]) == 1
    assert len(graph["nodes"]["Venue"]) == 2
    assert len(graph["nodes"]["Hotel"]) == 1
    assert len(graph["nodes"]["Event"]) == 2
    # A venue whose coordinate is not Verified must not look verified in the graph.
    by_id = {row["id"]: row for row in graph["nodes"]["Venue"]}
    assert by_id["v1"]["verified"] is True
    assert by_id["v2"]["verified"] is False
    # The hotel's grade comes from officialStar when present.
    assert graph["nodes"]["Hotel"][0]["star"] == 5


def test_edges_only_draw_what_the_data_states(db):
    graph = graph_sync.build_graph(db)
    pairs = {(edge["from"], edge["id"], edge["rel"], edge["toId"]) for edge in graph["edges"]}
    assert ("Event", "e1", "HELD_AT", "v1") in pairs
    assert ("Event", "e1", "IN_DISTRICT", "taicang") in pairs
    # e2 has neither a venue nor a district: it must produce no edges at all.
    assert not [edge for edge in graph["edges"] if edge["id"] == "e2"]
    # v2 has no district, so no IN_DISTRICT edge may be invented for it.
    assert not [edge for edge in graph["edges"]
                if edge["from"] == "Venue" and edge["id"] == "v2"]


def test_sync_is_derived_not_merged(db):
    """Everything the graph holds comes from the database; a re-run rebuilds it identically."""
    first = graph_sync.build_graph(db)
    second = graph_sync.build_graph(db)
    assert first == second
