"""Populate hotels from the AMap Web service, using its explicit star classification.

The demand analysis needs a hotel set, and inventing one would break the project's rule that
every record keeps a source. AMap publishes an explicit hotel grade in its POI type field
(``住宿服务;宾馆酒店;五星级宾馆``, ``四星级宾馆``, ``三星级宾馆``, ``经济型连锁酒店``), so the
three portfolio tiers are read from the source rather than judged here:

    高端   <- 五星级宾馆 / 豪华型
    中端   <- 四星级宾馆
    舒适   <- 三星级宾馆 / 经济型连锁酒店 / 商务酒店

Candidates are ranked by distance to the main event cluster around 金鸡湖, so the set is the
one that actually faces the city's event demand, and every row keeps its AMap place URL.

Dry-run by default; pass --apply to write. Requires AMAP_WEBSERVICE_KEY.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from backend.database import connect, snapshot  # noqa: E402

DEFAULT_DB = Path("backend/data/menduner.sqlite3")
POI_ENDPOINT = "https://restapi.amap.com/v3/place/text"
PLACE_URL = "https://ditu.amap.com/place/"
HOTEL_TYPES = "100000"
# The event cluster: 金鸡湖 / 苏州工业园区, where most Suzhou venues and exhibitions sit.
EVENT_CENTER = (120.702, 31.320)
# Radii are sampled around the districts that actually hold events, so the portfolio faces
# real demand rather than the far edge of the municipality.
EVENT_CLUSTERS = (
    (120.702, 31.320),  # 金鸡湖 / 国际博览中心 / 文化艺术中心
    (120.750, 31.305),  # 奥体中心
    (120.625, 31.310),  # 观前街 / 开明大戏院 / 姑苏古城
)
SUZHOU_AREAS = ("苏州市", "昆山市", "常熟市", "太仓市", "张家港市")
PER_TIER = 5
PAGES = 8

TIERS = (
    ("high", "高端", ("五星级宾馆", "豪华型")),
    ("mid", "中端", ("四星级宾馆",)),
    ("comfort", "舒适", ("三星级宾馆", "经济型连锁酒店", "商务酒店")),
)

# AMap states a grade for only a minority of hotels: many five-star properties are tagged
# merely 宾馆酒店. Rather than guess a tier, a row is only placed when the SOURCE or an
# explicit brand rule justifies it, and the justification is stored with the row.
LUXURY_BRANDS = (
    "W酒店", "洲际", "丽思卡尔顿", "瑞吉", "四季", "柏悦", "君悦", "香格里拉", "希尔顿",
    "万豪", "威斯汀", "喜来登", "艾美", "凯悦", "索菲特", "费尔蒙", "半岛", "文华东方",
    "安缦", "悦榕", "铂尔曼", "英迪格", "indigo", "泛太平洋", "豪生", "皇冠假日",
    "万丽", "金鸡湖大酒店", "日航", "大仓", "朗豪", "雅诗阁", "华邑", "希尔顿逸林",
    "凯宾斯基", "中茵皇冠", "兰博基尼", "尼依格罗", "苏州湾", "太湖万豪", "阳澄湖费尔蒙",
)
ECONOMY_BRANDS = (
    "汉庭", "如家", "7天", "布丁", "格林豪泰", "锦江之星", "莫泰", "宜必思", "尚客优",
    "贝壳", "速8", "城市便捷", "都市118",
)
MID_BRANDS = (
    "全季", "桔子", "亚朵", "维也纳", "丽枫", "希尔顿欢朋", "智选假日", "假日", "美居",
    "诺富特", "万怡", "凯莱", "戴斯", "宜尚", "君亭", "开元", "南苑", "书香", "智选",
    "丽呈", "美仑", "星程", "云上四季", "海友", "白玉兰", "锦江都城", "康铂", "希尔顿花园",
)

# POI entries that are lodging in AMap's taxonomy but are not hotels a revenue manager
# would put in a portfolio: hostels, apartments, homestays and banquet halls.
NOT_A_HOTEL = (
    "青年旅舍", "青旅", "民宿", "客栈", "公寓", "宴会", "婚礼", "餐厅", "食堂",
    "停车场", "售票", "入口", "出口", "店)",
)


def brand_rule(name: str, declared: str) -> tuple[str, str] | None:
    """A tier the source or an explicit brand rule justifies, with its justification."""
    lowered = name.casefold()
    if any(bad.casefold() in lowered for bad in NOT_A_HOTEL):
        return None
    if "五星级" in declared:
        return "high", "高德标注为五星级宾馆"
    if "四星级" in declared:
        return "mid", "高德标注为四星级宾馆"
    if any(brand.casefold() in lowered for brand in LUXURY_BRANDS):
        return "high", "酒店品牌为高端品牌"
    if any(brand.casefold() in lowered for brand in ECONOMY_BRANDS):
        return "comfort", "经济型连锁品牌"
    if any(brand.casefold() in lowered for brand in MID_BRANDS):
        return "mid", "中端连锁品牌"
    if "三星级" in declared or "经济型" in declared:
        return "comfort", "高德标注为经济型/三星级"
    return None


def load_key() -> str | None:
    key = os.environ.get("AMAP_WEBSERVICE_KEY")
    if key:
        return key.strip()
    env_file = Path(__file__).resolve().parent.parent / "frontend/.env.local"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("AMAP_WEBSERVICE_KEY="):
                return line.split("=", 1)[1].strip()
    return None


def distance_km(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    dl = math.radians(lat2 - lat1)
    dn = math.radians(lng2 - lng1)
    h = (
        math.sin(dl / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dn / 2) ** 2
    )
    return 6371 * 2 * math.asin(math.sqrt(min(1.0, h)))


def poi_tier(poi: dict) -> tuple[str, str] | None:
    """The tier this row can be justified at, with the justification, or None."""
    return brand_rule((poi.get("name") or "").strip(), f"{poi.get('type') or ''}")


def collect(client: httpx.Client, key: str) -> dict[str, list[dict]]:
    """Suzhou hotels per tier, sampled around the event clusters.

    Two queries are combined because neither alone is enough: a city-wide type search is
    capped at 600 results and is dominated by far-out budget properties, while a radius
    search returns the hotels that actually face the venues holding events.
    """
    found: dict[str, list[dict]] = {tier: [] for tier, _l, _m in TIERS}
    seen: set[str] = set()

    def absorb(pois: list[dict]) -> int:
        added = 0
        for poi in pois:
            poi_id = str(poi.get("id") or "")
            name = (poi.get("name") or "").strip()
            location = poi.get("location") or ""
            if not poi_id or not name or not location or poi_id in seen:
                continue
            seen.add(poi_id)
            if not any(area in (poi.get("cityname") or "") for area in SUZHOU_AREAS):
                continue
            declared = f"{poi.get('type') or ''}"
            decided = brand_rule(name, declared)
            if decided is None:
                continue
            tier, why = decided
            lng, lat = (float(x) for x in location.split(","))
            found[tier].append(
                {
                    "poi_id": poi_id,
                    "name": name,
                    "address": poi.get("address") if isinstance(poi.get("address"), str) else None,
                    "lng": lng,
                    "lat": lat,
                    "declared_type": declared,
                    "tier_why": why,
                    "adname": poi.get("adname"),
                    "distance_km": round(distance_km(lng, lat, *EVENT_CENTER), 2),
                }
            )
            added += 1
        return added

    # 1. Around the venues that actually hold events: 金鸡湖/博览中心, 奥体, 文化艺术中心.
    for cluster in EVENT_CLUSTERS:
        for page in range(1, 4):
            response = client.get(
                POI_ENDPOINT,
                params={
                    "key": key,
                    "types": HOTEL_TYPES,
                    "location": f"{cluster[0]},{cluster[1]}",
                    "radius": 6000,
                    "offset": 25,
                    "page": page,
                    "extensions": "all",
                },
            )
            document = response.json()
            if document.get("status") != "1":
                raise SystemExit(f"AMap error: {document.get('info')}")
            if not absorb(document.get("pois") or []):
                break
            time.sleep(0.3)

    # 2. City-wide, to reach properties the clusters do not contain.
    for page in range(1, PAGES + 1):
        response = client.get(
            POI_ENDPOINT,
            params={
                "key": key,
                "types": HOTEL_TYPES,
                "city": "苏州",
                "citylimit": "true",
                "offset": 25,
                "page": page,
                "extensions": "all",
            },
        )
        document = response.json()
        if document.get("status") != "1":
            raise SystemExit(f"AMap error: {document.get('info')}")
        pois = document.get("pois") or []
        if not pois:
            break
        absorb(pois)
        time.sleep(0.3)

    for tier in found:
        found[tier].sort(key=lambda row: row["distance_km"])
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--per-tier", type=int, default=PER_TIER)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    key = load_key()
    if not key:
        print("No AMAP_WEBSERVICE_KEY. Set it in the environment or frontend/.env.local.")
        return 2
    if not args.db.exists():
        print(f"missing database: {args.db}")
        return 1

    existing = {h["name"] for h in snapshot(args.db)["hotels"]}
    client = httpx.Client(timeout=25)
    try:
        found = collect(client, key)
    finally:
        client.close()

    print(f"database: {args.db}")
    print(f"existing hotels: {len(existing)}")
    chosen: list[dict] = []
    for tier, label, _markers in TIERS:
        rows = found.get(tier, [])
        print(f"\n== {label} ({tier}) · {len(rows)} 个候选, 取最近的 {args.per_tier} ==")
        picked = 0
        for row in rows:
            if picked >= args.per_tier:
                break
            if row["name"] in existing:
                print(f"   (已存在) {row['name']}")
                continue
            row["tier"] = tier
            row["tier_label"] = label
            chosen.append(row)
            picked += 1
            print(
                f"   {row['name'][:30]:30s} {row['adname'] or '':6s} "
                f"{row['distance_km']:5.2f}km  {row['tier_why']}"
            )

    print()
    print(f"total to add: {len(chosen)}")
    for tier, label, _m in TIERS:
        print(f"   {label}: {sum(1 for c in chosen if c['tier'] == tier)}")

    if not args.apply:
        print("\nDRY RUN: pass --apply to write these hotels")
        return 0

    with connect(args.db) as con:
        for row in chosen:
            hotel_id = "h-" + row["poi_id"].lower()
            payload = {
                "id": hotel_id,
                "name": row["name"],
                "address": row["address"],
                "districtId": None,
                "districtDemo": False,
                "tier": row["tier"],
                "tierLabel": row["tier_label"],
                # How the tier was decided, so it is checkable rather than assumed.
                "tierSource": row["tier_why"],
                "tierEvidence": row["declared_type"],
                "coordinates": {
                    "lng": row["lng"],
                    "lat": row["lat"],
                    "system": "GCJ-02",
                    "status": "Verified",
                    "sourceUrl": PLACE_URL + row["poi_id"],
                },
            }
            con.execute(
                "INSERT OR REPLACE INTO hotels(id,payload) VALUES(?,?)",
                (hotel_id, json.dumps(payload, ensure_ascii=False, sort_keys=True)),
            )
    print(f"\nAPPLIED: {len(chosen)} hotels added")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
