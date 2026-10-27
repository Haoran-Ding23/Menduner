"""为 GPT 知识图谱第 2 轮准备材料：数据模型 + 一条真实业务链 + 关系分类。

只读，不改库。输出直接贴给 GPT，所以每条关系都要标清「事实 / 计算 / 缺失」。
"""
import json
import math
import os
import sqlite3

DB = os.environ.get("MENDUNER_DB_PATH", "/srv/menduner/data/menduner.sqlite3")
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row


def rows(table):
    return [json.loads(r[0]) for r in con.execute(f"SELECT payload FROM {table}")]


def haversine(lng1, lat1, lng2, lat2):
    radius = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(2 * radius * math.asin(math.sqrt(a)))


print("== A. 数据模型 ==")
tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
print("  表:", ", ".join(tables))
for name in ("events", "venues", "hotels", "districts", "places", "sources", "evidence"):
    if name not in tables:
        continue
    cols = [(r[1], r[2]) for r in con.execute(f"PRAGMA table_info({name})")]
    count = con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
    print(f"  {name}({count} 行): " + ", ".join(f"{c}" for c, _ in cols))
foreign = [f"{r[2]}.{r[3]} -> {r[4]}" for r in con.execute("PRAGMA foreign_key_list(events)")]
print("  events 外键:", foreign or "无")

events = [dict(r) for r in con.execute(
    "SELECT id, name, COALESCE(canonical_id, id) AS identity, venue, district, source, "
    "verification_status, startDate, endDate FROM events")]
venues = {v["id"]: v for v in rows("venues")}
hotels = rows("hotels")
areas = [d for d in rows("districts") if d.get("kind") == "business_area" and (d.get("center") or {}).get("lng")]
places = rows("places")
sources = {r["id"]: dict(r) for r in con.execute("SELECT id, name, source_url FROM sources")}


def coords(payload):
    point = payload.get("coordinates") or {}
    if point.get("lng") is None:
        return None
    if str(point.get("system")).upper() != "GCJ-02" or str(point.get("status")) != "Verified":
        return None
    return float(point["lng"]), float(point["lat"])


print("\n== B. 一条真实业务链（不补造关系）==")
chain = None
for event in events:
    venue = venues.get(event.get("venue") or "")
    if not venue or coords(venue) is None:
        continue
    point = coords(venue)
    hotel = min(
        ((h, coords(h)) for h in hotels if coords(h)),
        key=lambda item: haversine(point[0], point[1], item[1][0], item[1][1]),
        default=None,
    )
    if not hotel:
        continue
    area = min(areas, key=lambda a: haversine(point[0], point[1], a["center"]["lng"], a["center"]["lat"]))
    chain = (event, venue, hotel, area, point)
    break

if chain:
    event, venue, (hotel, hotel_point), area, point = chain
    d_event_venue = "事实：活动表 venue 外键指向该场馆"
    d_venue_hotel = haversine(point[0], point[1], hotel_point[0], hotel_point[1])
    d_venue_area = haversine(point[0], point[1], area["center"]["lng"], area["center"]["lat"])
    near_places = sorted(
        ((p, coords(p)) for p in places if coords(p)),
        key=lambda item: haversine(point[0], point[1], item[1][0], item[1][1]),
    )[:3]
    print("  活动:", event["name"], "| id:", event["id"])
    print("   来源:", (sources.get(event.get("source") or "") or {}).get("name"), "| 核验状态:", event.get("verification_status"))
    print("  场馆:", venue.get("name"), "| id:", venue["id"], "| 坐标:", venue["coordinates"])
    print("   →", d_event_venue, "| 边的证据: events.venue 字段")
    print("  最近酒店:", hotel.get("name"), "| id:", hotel["id"], "| 距离:", d_venue_hotel, "米")
    print("   → 计算关系：球面距离，非业务联系（不表示该酒店会承接活动客源）")
    print("  最近商圈中心:", area.get("name"), f"（{area.get('status', 'official')}）", "| 距离:", d_venue_area, "米")
    print("   → 计算关系：距离 ≤ 该中心半径时才计入，否则为未匹配")
    print("  最近 POI（places）:")
    for poi, poi_point in near_places:
        if poi_point is None:
            continue
        print(f"    - {poi.get('name')}（{poi.get('type')}）距离 {haversine(point[0], point[1], poi_point[0], poi_point[1])} 米")
    print("   → 缺失关系：POI 与场馆/活动之间**没有任何已存储的关联边**，只能现场按距离计算")

print("\n== C. 关系分类统计 ==")
with_venue = sum(1 for e in events if e.get("venue") in venues)
with_coords = sum(1 for e in events if (venues.get(e.get("venue") or "") and coords(venues[e["venue"]])))
hotel_with_area = sum(1 for h in hotels if h.get("districtId"))
print(f"  事实边：活动→场馆 {with_venue}/{len(events)} 条（外键存储）")
print(f"  事实边：酒店→地区/商圈 {hotel_with_area}/{len(hotels)} 条（payload.districtId）")
print(f"  计算边：活动→（换算）场馆坐标可用 {with_coords} 条，距离全部现场计算，未落库")
print(f"  缺失边：POI({len(places)}) ↔ 场馆({len(venues)}) 无关联字段；客群为规则推断，无证据表")
