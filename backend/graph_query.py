"""图谱业务查询：把「活动—场馆—商圈—酒店」的关系按问题取出来。

## 为什么在 SQLite 上查而不是直接查 Neo4j

Neo4j 图是从这两张表派生出来的视图（backend/graph_sync.py），生产环境并没有部署 Neo4j。
把查询建在派生视图上，会得到一个「本地能跑、生产不能跑」的功能。所以查询直接读 SQLite ——
那里是事实的来源，图和查询因此永远一致。

## 每个结果都带出处

三类信息必须随结果返回，否则用户无法判断该不该信：
  * provenance：来源标识、更新时间、生成方式（采集 / 人工录入 / 规则推断）；
  * assumptions：规则推断出来的东西（例如客群匹配），明确标为假设；
  * missing：本该有但数据里没有的关系（活动没挂场馆、场馆没有坐标），显示「待补充」而不是省略。
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import date
from pathlib import Path

from backend.database import connect

# 客群推断规则：类别 → 客群。这是**规则**，不是采集到的字段，返回时必须标 assumption。
AUDIENCE_RULES: dict[str, str] = {
    "culture": "文化/休闲客群",
    "business": "商务客群",
    "sports": "赛事/运动客群",
    "religion": "民俗节庆客群",
    "education": "亲子/教育客群",
}

GENERATED_BY = {
    "event": "采集/人工录入（events 表）",
    "venue": "采集/人工录入（venues 表）",
    "hotel": "采集/人工录入（hotels 表）",
    "audience": "规则推断（按活动类别映射客群）",
    "distance": "计算（活动坐标与酒店坐标的球面距离）",
}


def _rows(con, table: str) -> dict[str, dict]:
    return {row["id"]: json.loads(row["payload"]) for row in con.execute(f"SELECT id, payload FROM {table}")}


def _event_node(row, venues: dict[str, dict], districts: dict[str, dict]) -> dict:
    venue = venues.get(row["venue"] or "")
    district = districts.get(row["district"] or "")
    return {
        "id": row["id"],
        "type": "Event",
        "label": row["name"],
        "startDate": row["startDate"],
        "endDate": row["endDate"],
        "category": row["category"],
        "provenance": {
            "source": row["source"],
            "updatedAt": row["updatedAt"] if "updatedAt" in row.keys() else None,
            "generatedBy": GENERATED_BY["event"],
        },
        "relations": {
            "heldAt": venue.get("name") if venue else None,
            "inDistrict": district.get("name") if district else None,
        },
        "audience": AUDIENCE_RULES.get(row["category"] or ""),
        "audienceIsAssumption": True,
    }


def venue_events(db_path: Path, venue_id: str, *, today: str | None = None, limit: int = 50) -> dict:
    """某个场馆有哪些活动（默认只看今天及以后）。"""
    stamp = today or date.today().isoformat()
    with connect(db_path) as con:
        venues, districts = _rows(con, "venues"), _rows(con, "districts")
        venue = venues.get(venue_id)
        if not venue:
            return {"ok": False, "reason": "场馆不存在"}
        events = [
            _event_node(row, venues, districts)
            for row in con.execute(
                "SELECT * FROM events WHERE venue=? AND COALESCE(endDate, startDate) >= ? "
                "ORDER BY startDate LIMIT ?", (venue_id, stamp, limit))
        ]
        missing = []
        if not events:
            in_db = con.execute("SELECT COUNT(*) FROM events WHERE venue=?", (venue_id,)).fetchone()[0]
            if in_db:
                missing.append("该场馆的活动都在今天之前结束")
        if not venue.get("districtId"):
            missing.append("该场馆未归属地区，无法关联商圈")
        if not (venue.get("coordinates") or {}).get("lng"):
            missing.append("该场馆缺少已核验坐标，无法计算距离")
    return {
        "ok": True,
        "query": "venue-events",
        "venue": {"id": venue_id, "name": venue.get("name")},
        "events": events,
        "counts": {"events": len(events)},
        "provenance": {"source": "venues / events 表", "generatedBy": "直接读取事实表"},
        "assumptions": ["客群标签由活动类别映射得出，属规则推断"],
        "missing": missing,
    }


def hotel_nearby_events(db_path: Path, hotel_id: str, *, radius_km: float = 10.0,
                        today: str | None = None, limit: int = 30) -> dict:
    """某酒店附近、按客群匹配的活动。

    客群是否匹配是规则推断（AUDIENCE_RULES），因此每条结果都带 audienceIsAssumption 标记；
    距离由坐标计算，缺坐标时该活动不被纳入，并计入 missing 说明排除了多少条。
    """
    stamp = today or date.today().isoformat()
    with connect(db_path) as con:
        venues, districts, hotels = _rows(con, "venues"), _rows(con, "districts"), _rows(con, "hotels")
        hotel = hotels.get(hotel_id)
        if not hotel:
            return {"ok": False, "reason": "酒店不存在"}
        hotel_coords = hotel.get("coordinates") or {}
        if hotel_coords.get("lng") is None:
            return {"ok": False, "reason": "酒店缺少已核验坐标，无法计算附近活动"}

        matched, excluded_no_coords, excluded_far = [], 0, 0
        for row in con.execute(
            "SELECT * FROM events WHERE COALESCE(endDate, startDate) >= ? ORDER BY startDate", (stamp,)):
            venue = venues.get(row["venue"] or "")
            coords = (venue or {}).get("coordinates") or {}
            if coords.get("lng") is None:
                excluded_no_coords += 1
                continue
            km = _haversine(hotel_coords["lng"], hotel_coords["lat"], coords["lng"], coords["lat"])
            if km > radius_km:
                excluded_far += 1
                continue
            node = _event_node(row, venues, districts)
            node["distanceKm"] = round(km, 2)
            matched.append(node)
        matched.sort(key=lambda item: item["distanceKm"])

    missing = []
    if excluded_no_coords:
        missing.append(f"另有 {excluded_no_coords} 场活动因场馆缺少坐标未能计算距离，已排除")
    return {
        "ok": True,
        "query": "hotel-nearby",
        "hotel": {"id": hotel_id, "name": hotel.get("name"), "districtId": hotel.get("districtId")},
        "radiusKm": radius_km,
        "events": matched[:limit],
        "counts": {"matched": len(matched), "excludedNoCoordinates": excluded_no_coords,
                   "excludedOutOfRadius": excluded_far},
        "provenance": {"source": "hotels / venues / events 表",
                       "generatedBy": GENERATED_BY["distance"]},
        "assumptions": [
            "客群标签由活动类别映射得出，属规则推断，不代表实际到访客群",
            f"半径 {radius_km:g} km 是本系统的展示口径，不是酒店自己的商圈定义",
        ],
        "missing": missing,
    }


def district_graph(db_path: Path, district_id: str) -> dict:
    """同一商圈（行政区/镇）里有哪些活动、场馆与酒店。"""
    with connect(db_path) as con:
        venues, districts, hotels = _rows(con, "venues"), _rows(con, "districts"), _rows(con, "hotels")
        district = districts.get(district_id)
        if not district:
            return {"ok": False, "reason": "地区不存在"}
        events = [_event_node(row, venues, districts) for row in con.execute(
            "SELECT * FROM events WHERE district=? ORDER BY startDate", (district_id,))]
        venue_list = [
            {
                "id": vid,
                "name": venue.get("name"),
                "hasCoordinates": bool((venue.get("coordinates") or {}).get("lng") is not None),
                "eventCount": sum(1 for event in events if event["relations"]["heldAt"] == venue.get("name")),
                "provenance": {"generatedBy": GENERATED_BY["venue"]},
            }
            for vid, venue in venues.items()
            if venue.get("districtId") == district_id
        ]
        hotel_list = [
            {
                "id": hid,
                "name": hotel.get("name"),
                "tierLabel": hotel.get("tierLabel"),
                "hasCoordinates": bool((hotel.get("coordinates") or {}).get("lng") is not None),
                "provenance": {"generatedBy": GENERATED_BY["hotel"]},
            }
            for hid, hotel in hotels.items()
            if hotel.get("districtId") == district_id
        ]

    missing = []
    if not venue_list:
        missing.append("该地区暂无已关联场馆")
    if not hotel_list:
        missing.append("该地区暂无已录入酒店")
    no_venue_events = sum(1 for event in events if not event["relations"]["heldAt"])
    if no_venue_events:
        missing.append(f"{no_venue_events} 场活动未关联场馆，关系待补充")

    categories = Counter(event["category"] for event in events if event["category"])
    return {
        "ok": True,
        "query": "district-graph",
        "district": {"id": district_id, "name": district.get("name"), "kind": district.get("kind")},
        "counts": {"events": len(events), "venues": len(venue_list), "hotels": len(hotel_list)},
        "categoryBreakdown": dict(categories),
        "events": events[:40],
        "venues": venue_list,
        "hotels": hotel_list,
        "provenance": {"source": "events / venues / hotels 表", "generatedBy": "直接读取事实表"},
        "assumptions": ["客群标签由活动类别映射得出，属规则推断"],
        "missing": missing,
    }


def _haversine(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    from math import asin, cos, radians, sin, sqrt

    d_lat = radians(lat2 - lat1)
    d_lng = radians(lng2 - lng1)
    a = sin(d_lat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lng / 2) ** 2
    return 6371.0 * 2 * asin(sqrt(a))
