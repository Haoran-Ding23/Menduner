"""商圈（business area）视角的聚合层。

核心约束（GPT Round 14 定下的口径，勿改）：
1. 商圈没有正式边界，我们只有「中心点 + 半径」。所以对外一律说
   **「商圈中心点周边活动（估算范围）」**，绝不说「商圈内活动」。
2. 距离不等于归属。落在半径内只记为 `nearby`；同时落在两个以上商圈的记为 `ambiguous`，
   **保留歧义、不硬挑最近的一个**；坐标缺失或超半径记为 `none`。
3. 只使用已核验坐标（status=Verified）且坐标系为 GCJ-02 的场馆。
4. 不覆盖任何已有 district 归属：本模块纯读，不改库。
5. 行政区口径与商圈口径分开统计，页面上不能相加、也不能互相冒充。
"""
from __future__ import annotations

import json
import math
from datetime import date

from backend.database import connect

DEFAULT_RADIUS = 800
COMPARISON_RADII = (800, 1200, 1500)
WEAK_POI_HINTS = ("地铁站", "村", "市", "路(", "(站)")


def haversine(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    """两点球面距离（米）。公式本身与坐标系无关，GCJ-02 内部一致即可。"""
    radius = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def load(db_path) -> dict:
    """读出商圈、场馆、活动、酒店的最小集合。"""
    with connect(db_path) as con:
        districts = [json.loads(row[0]) for row in con.execute("SELECT payload FROM districts")]
        venues = [json.loads(row[0]) for row in con.execute("SELECT payload FROM venues")]
        hotels = [json.loads(row[0]) for row in con.execute("SELECT payload FROM hotels")]
        columns = {row[1] for row in con.execute("PRAGMA table_info(events)")}
        canonical = "COALESCE(canonical_id, id)" if "canonical_id" in columns else "id"
        events = [dict(row) for row in con.execute(
            f"SELECT id, {canonical} AS identity, name, category, startDate, endDate, venue, "
            "district, source FROM events")]
    return {"districts": districts, "venues": venues, "hotels": hotels, "events": events}


def _coords(payload: dict) -> tuple[float, float] | None:
    coordinates = payload.get("coordinates") or {}
    if coordinates.get("lng") is None or coordinates.get("lat") is None:
        return None
    if str(coordinates.get("system") or "").upper() != "GCJ-02":
        return None          # 坐标系不明的不参与距离计算
    if str(coordinates.get("status") or "") != "Verified":
        return None          # 未核验坐标不参与
    return float(coordinates["lng"]), float(coordinates["lat"])


def area_quality(center: dict) -> str:
    """中心点质量：POI 名与商圈名明显不是一类东西时降级为 low。"""
    matched = str(center.get("matchedName") or "")
    name = str(center.get("areaName") or "")
    if any(hint in matched for hint in WEAK_POI_HINTS) and matched != name:
        return "low"
    return center.get("matchLevel") or "unverified"


def areas_with_center(data: dict, radius: int = DEFAULT_RADIUS) -> list[dict]:
    result = []
    for district in data["districts"]:
        if district.get("kind") != "business_area":
            continue
        center = district.get("center") or {}
        if center.get("lng") is None:
            continue
        center = dict(center)
        center["areaName"] = district.get("name")
        # official = 政府/地图方确认的名称；candidate = 我们用 POI 聚类得到的候选点
        status = district.get("status") or (
            "official" if center.get("matchLevel") in ("verified", "unverified") else "candidate"
        )
        result.append({
            "id": district["id"],
            "name": district.get("name"),
            "status": status,
            "parentId": district.get("parentId"),
            "adminCode": district.get("adminCode"),
            "center": center,
            "quality": area_quality(center),
            "radiusMeters": radius,
            "recordedRadiusMeters": int(center.get("radiusMeters") or radius),
        })
    return result


def assign(data: dict, radius: int = DEFAULT_RADIUS) -> dict:
    """把有坐标的活动分配到商圈，返回逐活动结果与统计。"""
    areas = areas_with_center(data, radius)
    venues = {v["id"]: v for v in data["venues"]}
    parents = {d["id"]: d.get("name") for d in data["districts"]}

    decisions: dict[str, dict] = {}
    for event in data["events"]:
        venue = venues.get(event.get("venue") or "")
        point = _coords(venue) if venue else None
        if point is None:
            decisions[event["identity"]] = {
                "identity": event["identity"], "matchLevel": "none",
                "reason": "场馆缺失" if not venue else "场馆坐标未核验或坐标系不明",
                "areas": [],
            }
            continue
        hits = []
        for area in areas:
            distance = haversine(point[0], point[1], area["center"]["lng"], area["center"]["lat"])
            if distance <= area["radiusMeters"]:
                hits.append({"id": area["id"], "name": area["name"], "distanceMeters": round(distance)})
        hits.sort(key=lambda item: item["distanceMeters"])
        if len(hits) == 1:
            level, reason = "nearby", "落在单一商圈中心点半径内（估算范围）"
        elif len(hits) > 1:
            level, reason = "ambiguous", f"同时落在 {len(hits)} 个商圈半径内，保留歧义不强行归属"
        else:
            level, reason = "none", "不在任何商圈中心点半径内"
        decisions[event["identity"]] = {
            "identity": event["identity"], "matchLevel": level, "reason": reason,
            "areas": hits,
        }

    counts = {"nearby": 0, "ambiguous": 0, "none": 0}
    for decision in decisions.values():
        counts[decision["matchLevel"]] += 1

    per_area: dict[str, dict] = {}
    for area in areas:
        per_area[area["id"]] = {"area": area, "nearby": [], "ambiguous": []}
    for event in data["events"]:
        decision = decisions[event["identity"]]
        for hit in decision["areas"]:
            bucket = "ambiguous" if decision["matchLevel"] == "ambiguous" else "nearby"
            per_area[hit["id"]][bucket].append({
                "identity": event["identity"], "name": event["name"], "category": event["category"],
                "startDate": event["startDate"], "endDate": event["endDate"],
                "district": event["district"], "distanceMeters": hit["distanceMeters"],
                "venue": event["venue"], "source": event["source"],
            })
    return {"areas": areas, "decisions": decisions, "counts": counts, "perArea": per_area,
            "parents": parents}


def usable_coord_identities(data: dict) -> int:
    """有多少去重身份的活动拿到了可用场馆坐标（Verified + GCJ-02）。"""
    venues = {v["id"]: v for v in data["venues"]}
    seen = set()
    for event in data["events"]:
        venue = venues.get(event.get("venue") or "")
        if venue and _coords(venue):
            seen.add(event["identity"])
    return len(seen)


def coverage(db_path, radius: int = DEFAULT_RADIUS) -> dict:
    data = load(db_path)
    result = assign(data, radius)
    venues_with_coords = sum(1 for v in data["venues"] if _coords(v))
    total_identities = len({e["identity"] for e in data["events"]})
    comparisons = []
    for value in COMPARISON_RADII:
        other = result if value == radius else assign(data, value)
        comparisons.append({
            "radiusMeters": value,
            "uniqueNear": other["counts"]["nearby"],
            "ambiguous": other["counts"]["ambiguous"],
            "unmatched": other["counts"]["none"],
        })
    return {
        "radiusMeters": radius,
        "radiusLabel": "近邻分析范围（未经验证的商圈边界）",
        "identitiesTotal": total_identities,
        "coordsUsable": usable_coord_identities(data),
        "comparisons": comparisons,
        "areaCount": len(result["areas"]),
        "areaWithCenter": len(result["areas"]),
        "areaVerified": sum(1 for a in result["areas"] if a["quality"] == "verified"),
        "officialCount": sum(1 for a in result["areas"] if a["status"] == "official"),
        "candidateCount": sum(1 for a in result["areas"] if a["status"] == "candidate"),
        "areaLowQuality": sum(1 for a in result["areas"] if a["quality"] == "low"),
        "venuesTotal": len(data["venues"]),
        "venuesWithVerifiedCoords": venues_with_coords,
        "eventsTotal": total_identities,
        "eventsNearby": result["counts"]["nearby"],
        "eventsAmbiguous": result["counts"]["ambiguous"],
        "eventsUnmatched": result["counts"]["none"],
        "note": "商圈无正式边界；这里的数字是「商圈中心点周边活动（估算范围）」，不是商圈内活动总量。",
    }


def ranking(db_path, radius: int = DEFAULT_RADIUS) -> list[dict]:
    data = load(db_path)
    result = assign(data, radius)
    rows = []
    for area_id, bucket in result["perArea"].items():
        area = bucket["area"]
        parent_events = sum(1 for e in data["events"] if e["district"] == area["parentId"])
        rows.append({
            "id": area_id,
            "name": area["name"],
            "status": area["status"],
            "parentName": result["parents"].get(area["parentId"]),
            "quality": area["quality"],
            "centerSource": area["center"].get("source"),
            "radiusMeters": area["radiusMeters"],
            "nearbyEvents": len(bucket["nearby"]),
            "ambiguousEvents": len(bucket["ambiguous"]),
            "parentDistrictEvents": parent_events,
        })
    rows.sort(key=lambda row: (-row["nearbyEvents"], row["name"] or ""))
    return rows


def profile(db_path, area_id: str, radius: int = DEFAULT_RADIUS,
            start: str | None = None, end: str | None = None) -> dict:
    data = load(db_path)
    result = assign(data, radius)
    bucket = result["perArea"].get(area_id)
    if bucket is None:
        raise KeyError(area_id)
    area = bucket["area"]
    window = {"start": start, "end": end}

    def in_window(item: dict) -> bool:
        begin = item.get("startDate")
        if not begin:
            return False
        finish = item.get("endDate") or begin
        if finish < begin:
            finish = begin
        if start and finish < start:
            return False
        if end and begin > end:
            return False
        return True

    nearby = [item for item in bucket["nearby"] if in_window(item)]
    ambiguous = [item for item in bucket["ambiguous"] if in_window(item)]

    categories: dict[str, int] = {}
    months: dict[str, int] = {}
    for item in nearby:
        categories[item["category"] or "未分类"] = categories.get(item["category"] or "未分类", 0) + 1
        month = (item.get("startDate") or "")[:7]
        if month:
            months[month] = months.get(month, 0) + 1

    hotels = []
    for hotel in data["hotels"]:
        point = _coords(hotel)
        if point is None:
            continue
        distance = haversine(point[0], point[1], area["center"]["lng"], area["center"]["lat"])
        if distance <= area["radiusMeters"]:
            hotels.append({"name": hotel.get("name"), "distanceMeters": round(distance),
                           "starLabel": hotel.get("starLabel")})
    hotels.sort(key=lambda item: item["distanceMeters"])

    parent_events = sum(1 for e in data["events"] if e["district"] == area["parentId"])

    # 供给画像：只描述「我们观测到的活动供给」，不叫消费、不叫经济贡献
    covered_days = 0
    for item in nearby:
        begin = item.get("startDate")
        if not begin:
            continue
        finish = item.get("endDate") or begin
        if finish < begin:
            finish = begin
        if start and begin < start:
            begin = start
        if end and finish > end:
            finish = end
        try:
            covered_days += max(0, (date.fromisoformat(finish) - date.fromisoformat(begin)).days + 1)
        except ValueError:
            continue
    venue_ids = {item.get("venue") for item in nearby if item.get("venue")}
    with_source_url = 0
    if nearby:
        with connect(db_path) as con:
            source_rows = {row[0]: row[1] for row in con.execute("SELECT id, source_url FROM sources")}
        for item in nearby:
            if source_rows.get(item.get("source")):
                with_source_url += 1

    return {
        "area": {
            "id": area_id, "name": area["name"], "status": area["status"],
            "parentName": result["parents"].get(area["parentId"]),
            "quality": area["quality"], "radiusMeters": area["radiusMeters"],
            "center": {
                "lng": area["center"]["lng"], "lat": area["center"]["lat"],
                "system": area["center"].get("system"), "source": area["center"].get("source"),
                "matchedName": area["center"].get("matchedName"),
                "adname": area["center"].get("adname"),
                "matchLevel": area["center"].get("matchLevel"),
                "matchedAt": area["center"].get("matchedAt"),
            },
        },
        "window": window,
        "nearbyEvents": nearby,
        "ambiguousEvents": ambiguous,
        "coverage": {
            "method": "场馆已核验坐标（GCJ-02）到商圈中心点的球面距离 ≤ 半径",
            "matched": len(nearby),
            "matchedAll": len(bucket["nearby"]),
            "ambiguous": len(ambiguous),
            "ambiguousAll": len(bucket["ambiguous"]),
            "parentDistrictEvents": parent_events,
            "unmatchedInParent": max(0, parent_events - len(bucket["nearby"]) - len(bucket["ambiguous"])),
            "venuesWithVerifiedCoords": sum(1 for v in data["venues"] if _coords(v)),
            "venuesTotal": len(data["venues"]),
        },
        "supplyProfile": {
            "uniqueActivities": len(nearby),
            "coveredDays": covered_days,
            "venues": len(venue_ids),
            "sourceCoverageRate": round(with_source_url / len(nearby), 3) if nearby else 0.0,
            "spatialMatchRate": round(len(nearby) / parent_events, 3) if parent_events else 0.0,
            "ambiguityRate": round(len(ambiguous) / (len(nearby) + len(ambiguous)), 3)
            if (nearby or ambiguous) else 0.0,
            "note": "供给画像只描述我们观测到的活动供给，不代表消费额、客流或经济贡献。",
        },
        "categories": sorted(categories.items(), key=lambda kv: -kv[1]),
        "months": sorted(months.items()),
        "hotels": hotels,
        "caveat": "商圈无正式边界，以上是中心点周边估算范围；未匹配不等于该商圈没有活动。",
    }


def month_bounds(today: str | None = None) -> tuple[str, str]:
    day = date.fromisoformat(today) if today else date.today()
    first = day.replace(day=1)
    next_month = (first.replace(year=first.year + 1, month=1) if first.month == 12
                  else first.replace(month=first.month + 1))
    last = next_month.toordinal() - 1
    return first.isoformat(), date.fromordinal(last).isoformat()
