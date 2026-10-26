"""商圈聚合的测试（GPT Round 14 的三条验收）。

重点不是"能跑"，而是三类边界：
  1. 距离只是估算范围，落在两个商圈里必须保留歧义，不能硬挑最近的；
  2. 未核验坐标、坐标系不明、场馆缺失都不参与，且不会"解释成该商圈没有活动"；
  3. 原有 district 归属不被覆盖，行政区口径与商圈口径分开。
"""
import json

import pytest

from backend import market_area
from backend.database import connect, initialize

RADIUS = 1200


def add_venue(con, venue_id, lng, lat, status="Verified", system="GCJ-02"):
    con.execute("INSERT INTO venues(id,payload) VALUES(?,?)", (venue_id, json.dumps({
        "id": venue_id, "name": f"场馆-{venue_id}",
        "coordinates": {"lng": lng, "lat": lat, "system": system, "status": status},
    }, ensure_ascii=False)))


def add_area(con, area_id, name, lng, lat, parent="gusu", radius=RADIUS, match="verified"):
    con.execute("INSERT INTO districts(id,payload) VALUES(?,?)", (area_id, json.dumps({
        "id": area_id, "name": name, "kind": "business_area", "parentId": parent,
        "center": {"lng": lng, "lat": lat, "system": "GCJ-02", "source": "amap-place-text",
                   "radiusMeters": radius, "matchLevel": match, "matchedName": name,
                   "adname": "姑苏区"},
    }, ensure_ascii=False)))


def add_event(con, event_id, venue, district="gusu", start="2026-11-10", end=None):
    con.execute(
        "INSERT INTO events(id,name,category,startDate,endDate,venue,district,source,"
        "verification_status,payload) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (event_id, f"活动-{event_id}", "culture", start, end, venue, district, "s1",
         "Needs Review", "{}"))


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "main.sqlite3"
    initialize(path)
    with connect(path) as con:
        con.execute("INSERT INTO sources VALUES(?,?,?,?,?,?)",
                    ("s1", "来源", "government", 0, "https://a.test", "2026-10-01T00:00:00+00:00"))
        # 父级行政区必须先存在（events.district 有外键）
        con.execute("INSERT INTO districts(id,payload) VALUES(?,?)",
                    ("gusu", json.dumps({"id": "gusu", "name": "姑苏区", "kind": "district"},
                                         ensure_ascii=False)))
        # 两个相距约 1 km 的商圈，中间放一个场馆 → 应判为歧义
        add_area(con, "area-a", "观前", 120.6200, 31.3100)
        add_area(con, "area-b", "平江", 120.6400, 31.3100)
        add_venue(con, "v-mid", 120.6300, 31.3100)
        # 只属于 area-a 的场馆
        add_venue(con, "v-a", 120.6205, 31.3105)
        # 半径外
        add_venue(con, "v-far", 120.7000, 31.4000)
        # 未核验坐标
        add_venue(con, "v-unverified", 120.6200, 31.3100, status="Needs Review")
        # 坐标系不明
        add_venue(con, "v-wgs", 120.6200, 31.3100, system="WGS-84")
    return path


def test_boundary_and_ambiguity(db):
    with connect(db) as con:
        add_event(con, "e-mid", "v-mid")
        add_event(con, "e-a", "v-a")
        add_event(con, "e-far", "v-far")
        add_event(con, "e-novenu", None)
    result = market_area.assign(market_area.load(db), RADIUS)
    levels = {key: value["matchLevel"] for key, value in result["decisions"].items()}
    assert levels["e-mid"] == "ambiguous"        # 同时落进两个商圈：保留歧义
    assert levels["e-a"] == "nearby"
    assert levels["e-far"] == "none"
    assert levels["e-novenu"] == "none"
    assert result["counts"]["ambiguous"] == 1
    # 歧义活动同时出现在两个商圈的 ambiguous 桶里，而不是被塞进某一个 nearby
    assert len(result["perArea"]["area-a"]["ambiguous"]) == 1
    assert len(result["perArea"]["area-b"]["ambiguous"]) == 1
    assert result["perArea"]["area-a"]["nearby"][0]["name"] == "活动-e-a"


def test_unverified_or_unknown_coordinates_are_excluded(db):
    with connect(db) as con:
        add_event(con, "e-unverified", "v-unverified")
        add_event(con, "e-wgs", "v-wgs")
    result = market_area.assign(market_area.load(db), RADIUS)
    for identity in ("e-unverified", "e-wgs"):
        assert result["decisions"][identity]["matchLevel"] == "none"
        assert "坐标" in result["decisions"][identity]["reason"]


def test_radius_sensitivity_changes_assignment(db):
    with connect(db) as con:
        add_event(con, "e-mid", "v-mid")
    near = market_area.assign(market_area.load(db), 300)
    far = market_area.assign(market_area.load(db), 1500)
    # 半径 300m 时中间点不会同时落入两个商圈
    assert near["counts"]["ambiguous"] == 0
    assert far["counts"]["ambiguous"] >= 1


def test_district_attribution_untouched(db):
    with connect(db) as con:
        add_event(con, "e-a", "v-a", district="gusu")
    before = json.loads(_event_payload(db, "e-a"))
    market_area.coverage(db, RADIUS)
    after = json.loads(_event_payload(db, "e-a"))
    assert before == after
    with connect(db) as con:
        assert con.execute("SELECT district FROM events WHERE id='e-a'").fetchone()[0] == "gusu"


def _event_payload(path, event_id):
    with connect(path) as con:
        return con.execute("SELECT payload FROM events WHERE id=?", (event_id,)).fetchone()[0]


def test_profile_reports_denominator_and_method(db):
    with connect(db) as con:
        add_event(con, "e-a", "v-a")
        add_event(con, "e-mid", "v-mid")
        add_event(con, "e-far", "v-far")
    profile = market_area.profile(db, "area-a", RADIUS)
    assert profile["area"]["name"] == "观前"
    assert profile["coverage"]["matched"] == 1
    assert profile["coverage"]["ambiguous"] == 1
    # 分母是父级行政区活动数，用来提醒"不是全覆盖"
    assert profile["coverage"]["parentDistrictEvents"] == 3
    assert "估算范围" in profile["coverage"]["method"] or "估算" in profile["caveat"]
    assert profile["coverage"]["venuesWithVerifiedCoords"] >= 2
    assert "未匹配不等于" in profile["caveat"]


def test_window_filter_only_affects_profile(db):
    with connect(db) as con:
        add_event(con, "e-a", "v-a", start="2026-11-10", end="2026-11-12")
        add_event(con, "e-b", "v-a", start="2026-12-01")
    inside = market_area.profile(db, "area-a", RADIUS, start="2026-11-01", end="2026-11-30")
    outside = market_area.profile(db, "area-a", RADIUS, start="2027-01-01", end="2027-01-31")
    assert len(inside["nearbyEvents"]) == 1
    assert len(outside["nearbyEvents"]) == 0
    # 覆盖率里的 matchedAll 是数据能力指标，不随窗口变化；matched 才是窗口内计数
    assert inside["coverage"]["matched"] == 1  # 12 月那条不在 11 月窗口内
    assert outside["coverage"]["matched"] == 0
    assert inside["coverage"]["matchedAll"] == outside["coverage"]["matchedAll"] == 2


def test_low_quality_poi_is_flagged(db):
    with connect(db) as con:
        add_area(con, "area-c", "南门", 120.6150, 31.3200)
    with connect(db) as con:
        payload = json.loads(con.execute("SELECT payload FROM districts WHERE id='area-c'").fetchone()[0])
        payload["center"]["matchedName"] = "南门(地铁站)"
        con.execute("UPDATE districts SET payload=? WHERE id='area-c'",
                    (json.dumps(payload, ensure_ascii=False),))
    rows = {row["id"]: row for row in market_area.ranking(db, RADIUS)}
    assert rows["area-c"]["quality"] == "low"


def test_ranking_sorted_by_nearby_then_name(db):
    with connect(db) as con:
        add_event(con, "e-a", "v-a")
        add_event(con, "e-a2", "v-a")
    rows = market_area.ranking(db, RADIUS)
    assert rows[0]["id"] == "area-a"
    assert rows[0]["nearbyEvents"] == 2
    assert rows[0]["parentName"] == "姑苏区"

def test_supply_profile_is_not_consumption(db):
    """GPT Round 15：替代指标是「供给画像」，不能出现消费额/客流字样。"""
    with connect(db) as con:
        add_event(con, "e-a", "v-a", start="2026-11-10", end="2026-11-12")
    profile = market_area.profile(db, "area-a", 800)
    supply = profile["supplyProfile"]
    assert supply["uniqueActivities"] == 1
    assert supply["coveredDays"] == 3
    assert supply["venues"] == 1
    assert 0 <= supply["sourceCoverageRate"] <= 1
    assert 0 <= supply["ambiguityRate"] <= 1
    assert "消费" in supply["note"] and "经济贡献" in supply["note"]
    assert "消费额" not in str(profile["categories"])


def test_coverage_reports_comparisons_and_usable_coords(db):
    with connect(db) as con:
        add_event(con, "e-a", "v-a")
    coverage = market_area.coverage(db, 800)
    assert coverage["radiusLabel"].startswith("近邻分析范围")
    assert coverage["identitiesTotal"] >= 1
    assert coverage["coordsUsable"] >= 1
    radii = [row["radiusMeters"] for row in coverage["comparisons"]]
    assert radii == [800, 1200, 1500]
    for row in coverage["comparisons"]:
        assert set(row) >= {"uniqueNear", "ambiguous", "unmatched"}
