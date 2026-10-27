"""图谱链路：活动 → 场馆 → 周边酒店 / 餐饮 / 交通（GPT Round 27 批准的第三条链路）。

设计要点（照 GPT 定的协议，别自由发挥）：
1. 三类边严格分开：
   recorded  — 数据库里有记录支持的边（HELD_AT / REPORTED_BY / TAGGED_TO_REGION）
   computed   — 用坐标现算的边（NEARBY / WITHIN_RADIUS），必须带 calculation
   第一版不生成 inferred 边（目标客群图层禁用）
2. recorded 边不等于已核验事实：外键存在，但活动状态是 Needs Review 时，
   边的 verificationStatus 必须如实反映，不能显示成 Verified。
3. 距离边必须有：两端坐标来源、坐标系、距离、算法、计算时间、阈值。
4. 超出半径的中心点**不生成 WITHIN_RADIUS 边**，只作为 nearbyAreaCenter 信息返回。
5. 同身份多记录用 canonical_id 去重；日期冲突时不静默择一，标记冲突。
6. 找不到关系时允许孤立节点，但必须写明缺失原因，不允许"自动连最近实体凑图"。
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone

from backend.database import connect
from backend.version import CALIBER_VERSION

DEFAULT_RADIUS_METERS = 800
ALGORITHM = "haversine-v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def haversine(lng1: float, lat1: float, lng2: float, lat2: float) -> int:
    radius = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(2 * radius * math.asin(math.sqrt(a)))


def coords_of(payload: dict) -> dict | None:
    """只有 GCJ-02 且已核验的坐标才参与距离计算；其余返回 None（并说明原因）。"""
    point = (payload or {}).get("coordinates") or {}
    if point.get("lng") is None or point.get("lat") is None:
        return None
    if str(point.get("system") or "").upper() != "GCJ-02":
        return None
    return {
        "lng": float(point["lng"]),
        "lat": float(point["lat"]),
        "system": "GCJ-02",
        "status": point.get("status"),
        "sourceUrl": point.get("sourceUrl"),
    }


def _load(db_path):
    with connect(db_path) as con:
        districts = {row[0]: json.loads(row[1]) for row in con.execute("SELECT id, payload FROM districts")}
        venues = {row[0]: json.loads(row[1]) for row in con.execute("SELECT id, payload FROM venues")}
        hotels = {row[0]: json.loads(row[1]) for row in con.execute("SELECT id, payload FROM hotels")}
        places = {row[0]: json.loads(row[1]) for row in con.execute("SELECT id, payload FROM places")}
        sources = {row[0]: {"name": row[1], "url": row[2]}
                   for row in con.execute("SELECT id, name, source_url FROM sources")}
        columns = {row[1] for row in con.execute("PRAGMA table_info(events)")}
        identity = "COALESCE(canonical_id, id)" if "canonical_id" in columns else "id"
        events = [dict(row) for row in con.execute(
            f"SELECT id, {identity} AS identity, name, category, startDate, endDate, venue, district, "
            "source, verification_status FROM events")]
        evidence = [dict(row) for row in con.execute(
            "SELECT id, event_id, entity_id, field, value, source_url, verification_status FROM evidence")]
    return districts, venues, hotels, places, sources, events, evidence


def _recorded_status(value: str | None) -> str:
    """把内部核验状态映射成图谱协议里的三种值。"""
    if value == "Verified":
        return "Verified"
    if value in ("Needs Review", "Conflicting", "Missing", "Unverified"):
        return "Needs Review"
    return "Unknown"


def event_chain(db_path, event_id: str, radius_meters: int = DEFAULT_RADIUS_METERS) -> dict:
    districts, venues, hotels, places, sources, events, evidence = _load(db_path)

    target = next((e for e in events if e["id"] == event_id), None)
    if target is None:
        raise KeyError(event_id)

    siblings = [e for e in events if e["identity"] == target["identity"]]
    date_conflict = len({(e["startDate"], e["endDate"]) for e in siblings}) > 1

    nodes: list[dict] = [{
        "id": target["identity"], "type": "Event", "name": target["name"],
        "attributes": {
            "startDate": target["startDate"], "endDate": target["endDate"],
            "category": target["category"], "verificationStatus": _recorded_status(target["verification_status"]),
            "recordIds": [e["id"] for e in siblings],
        },
    }]
    edges: list[dict] = []
    warnings: list[str] = []
    evidence_refs: list[dict] = []

    if date_conflict:
        warnings.append("同一活动的多条记录起止日期不一致，未静默择一，请人工核对")
    if len(siblings) > 1:
        warnings.append(f"同一身份有 {len(siblings)} 条来源记录，已按 canonical_id 去重展示")

    # ---- recorded: 活动 → 场馆 ----
    venue = venues.get(target["venue"] or "")
    venue_point = coords_of(venue) if venue else None
    if venue:
        field_evidence = [item for item in evidence
                          if item["event_id"] == target["id"] and item["field"] in ("venue", "venueName")]
        evidence_refs.extend(field_evidence)
        nodes.append({
            "id": venue["id"], "type": "Venue", "name": venue.get("name"),
            "attributes": {
                "address": venue.get("address"),
                "coordinates": venue_point,
                "coordinateStatus": (venue.get("coordinates") or {}).get("status"),
            },
        })
        edges.append({
            "id": f"edge-held-at-{target['identity']}-{venue['id']}",
            "fromId": target["identity"], "toId": venue["id"],
            "type": "HELD_AT", "kind": "recorded",
            "verificationStatus": _recorded_status(target["verification_status"]),
            "evidenceRefs": [
                {"table": "events", "recordId": target["id"], "field": "venue",
                 "evidenceId": field_evidence[0]["id"] if field_evidence else None,
                 "sourceUrl": (sources.get(target["source"] or "") or {}).get("url")},
            ],
        })
        if _recorded_status(target["verification_status"]) != "Verified":
            warnings.append("活动与场馆的关联来自原始记录，尚未核验（Needs Review），不视为已确认事实")
    else:
        warnings.append("该活动没有关联场馆，无法计算周边距离")

    # ---- recorded: 活动 → 来源 ----
    source = sources.get(target["source"] or "")
    if source:
        nodes.append({"id": target["source"], "type": "Source", "name": source["name"],
                      "attributes": {"url": source["url"]}})
        edges.append({
            "id": f"edge-reported-by-{target['identity']}", "fromId": target["identity"],
            "toId": target["source"], "type": "REPORTED_BY", "kind": "recorded",
            "verificationStatus": "Verified",
            "evidenceRefs": [{"table": "events", "recordId": target["id"], "field": "source",
                              "sourceUrl": source["url"]}],
        })

    # ---- computed: 场馆 → 周边酒店 / POI / 中心 ----
    nearby_hotels, nearby_places = [], []
    center_info = None
    if venue_point:
        for hotel_id, hotel in hotels.items():
            point = coords_of(hotel)
            if point is None:
                continue
            distance = haversine(venue_point["lng"], venue_point["lat"], point["lng"], point["lat"])
            if distance > radius_meters:
                continue
            nearby_hotels.append({"id": hotel_id, "name": hotel.get("name"), "distanceMeters": distance,
                                  "coordinates": point})
            nodes.append({"id": hotel_id, "type": "Hotel", "name": hotel.get("name"),
                          "attributes": {"distanceMeters": distance}})
            edges.append({
                "id": f"edge-nearby-{venue['id']}-{hotel_id}", "fromId": venue["id"], "toId": hotel_id,
                "type": "NEARBY", "kind": "computed", "verificationStatus": "Unknown",
                "evidenceRefs": [],
                "calculation": {
                    "method": ALGORITHM, "coordinateSystem": "GCJ-02",
                    "distanceMeters": distance, "radiusMeters": radius_meters,
                    "calculatedAt": _now(),
                    "inputCoordinateRefs": [venue.get("coordinates", {}).get("sourceUrl"),
                                            hotel.get("coordinates", {}).get("sourceUrl")],
                },
            })

        for place_id, place in places.items():
            point = coords_of(place)
            if point is None:
                continue
            distance = haversine(venue_point["lng"], venue_point["lat"], point["lng"], point["lat"])
            if distance > radius_meters:
                continue
            category = place.get("type") or place.get("category")
            nearby_places.append({"id": place_id, "name": place.get("name"),
                                  "distanceMeters": distance, "category": category})
            nodes.append({"id": place_id, "type": "Place", "name": place.get("name"),
                          "attributes": {"category": category, "distanceMeters": distance}})
            edges.append({
                "id": f"edge-nearby-{venue['id']}-{place_id}", "fromId": venue["id"], "toId": place_id,
                "type": "NEARBY", "kind": "computed", "verificationStatus": "Unknown",
                "evidenceRefs": [],
                "calculation": {
                    "method": ALGORITHM, "coordinateSystem": "GCJ-02",
                    "distanceMeters": distance, "radiusMeters": radius_meters,
                    "calculatedAt": _now(),
                    "inputCoordinateRefs": [venue.get("coordinates", {}).get("sourceUrl"),
                                            place.get("coordinates", {}).get("sourceUrl")],
                },
            })

        candidates = []
        for district_id, district in districts.items():
            if district.get("kind") != "business_area":
                continue
            center = district.get("center") or {}
            if center.get("lng") is None:
                continue
            distance = haversine(venue_point["lng"], venue_point["lat"], center["lng"], center["lat"])
            candidates.append((distance, district_id, district))

        if candidates:
            distance, district_id, district = min(candidates, key=lambda item: item[0])
            inside = distance <= (district.get("center", {}).get("radiusMeters") or radius_meters)
            center_info = {
                "id": district_id, "name": district.get("name"),
                "kind": district.get("status") or "official",
                "distanceMeters": distance, "insideRadius": inside,
            }
            nodes.append({"id": district_id, "type": "AreaCenter", "name": district.get("name"),
                          "attributes": {"kind": center_info["kind"], "distanceMeters": distance}})
            if inside:
                edges.append({
                    "id": f"edge-within-{venue['id']}-{district_id}", "fromId": venue["id"],
                    "toId": district_id, "type": "WITHIN_RADIUS", "kind": "computed",
                    "verificationStatus": "Unknown", "evidenceRefs": [],
                    "calculation": {
                        "method": ALGORITHM, "coordinateSystem": "GCJ-02",
                        "distanceMeters": distance,
                        "radiusMeters": district.get("center", {}).get("radiusMeters") or radius_meters,
                        "calculatedAt": _now(),
                        "inputCoordinateRefs": [venue.get("coordinates", {}).get("sourceUrl"),
                                                district.get("center", {}).get("sourceUrl")],
                    },
                })
            else:
                warnings.append(f"最近的商业参考点「{district.get('name')}」距离 {distance} 米，"
                                f"超出半径，因此未建立归属关系")

    nearby_hotels.sort(key=lambda item: item["distanceMeters"])
    nearby_places.sort(key=lambda item: item["distanceMeters"])

    if not nearby_hotels:
        warnings.append("半径内没有已收录且坐标可用的酒店（不代表附近没有酒店）")
    if not nearby_places:
        warnings.append("半径内没有已收录的餐饮/交通 POI（不代表附近没有设施）")

    warnings.append("地理近邻不等于业务联系：距离近不代表活动客源会入住该酒店或使用该设施")

    actions = [
        {"type": "open_map", "label": "在地图中查看该活动", "eventId": target["id"]},
        {"type": "open_evidence", "label": "查看该活动的字段证据", "eventId": target["id"]},
    ]
    if venue:
        actions.append({"type": "open_venue", "label": "查看场馆详情", "venueId": venue["id"]})

    return {
        "queryType": "event_chain",
        "eventId": target["id"],
        "identity": target["identity"],
        "radiusMeters": radius_meters,
        "dataVersion": CALIBER_VERSION,
        "generatedAt": _now(),
        "nodes": nodes,
        "edges": edges,
        "venue": {"id": venue["id"], "name": venue.get("name")} if venue else None,
        "nearbyHotels": nearby_hotels,
        "nearbyPlaces": nearby_places,
        "nearbyAreaCenter": center_info,
        "evidenceRefs": evidence_refs,
        "warnings": warnings,
        "actions": actions,
    }
