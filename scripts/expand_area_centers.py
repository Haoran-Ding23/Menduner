"""用高德 POI 聚类补充「候选商业集聚点」，而不是伪造商圈。

GPT Round 15 的规则（照做）：
  * 允许 DBSCAN / 空间聚类识别商业集聚点，但**不得冒充正式商圈**；
  * 命名优先用地图已有名称，否则标成「XX 周边·候选商业集聚点」；
  * 簇间最小间距只是去重参考，不强制合并；道路/河流阻隔不强行合并；
  * 记录 POI 来源、算法参数、核验状态；
  * 40–60 个不是必须完成的数量指标。

实现：贪心聚类（比 DBSCAN 透明、参数可解释）。
  1. 按关键词抓 POI（购物中心 / 百货 / 商业广场 / 商业街），保留 name/address/adname/location/type；
  2. 以 800 m 为簇半径贪心聚合，簇中心取成员坐标均值；
  3. 与已有 20 个官方商圈中心距离 < 1.2 km 的簇**丢弃**（避免重复定义同一个地方）；
  4. 簇内成员数 >= 2 才保留（单个 POI 不算集聚）；
  5. 写入 districts：kind=business_area，id=area-poi-<序号>，center.matchLevel=candidate，
     center.algorithm 记录半径/最小成员数/成员数与抓取关键词。

用法：
  python scripts/expand_area_centers.py --dry-run
  python scripts/expand_area_centers.py --apply
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database import connect, database_path  # noqa: E402

KEY = os.environ.get("AMAP_WEBSERVICE_KEY", "").strip()
ENDPOINT = "https://restapi.amap.com/v3/place/text"
KEYWORDS = ["购物中心", "百货商场", "商业广场", "商业街"]
CITIES = ["苏州", "太仓"]
CLUSTER_RADIUS = 800          # 簇内聚合半径
MIN_MEMBERS = 2               # 至少两个 POI 才算集聚
OFFICIAL_GAP = 1200           # 与已有官方商圈中心的最小距离
MAX_CANDIDATES = 45           # 上限，避免无限膨胀


def haversine(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    radius = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def fetch(keyword: str, city: str, page: int) -> list[dict]:
    query = urllib.parse.urlencode({
        "key": KEY, "keywords": keyword, "city": city, "citylimit": "true",
        "offset": "25", "page": str(page), "extensions": "base",
    })
    with urllib.request.urlopen(f"{ENDPOINT}?{query}", timeout=25) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload.get("pois") or []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.apply and not args.dry_run:
        args.dry_run = True
    if args.apply and not KEY:
        print("缺少 AMAP_WEBSERVICE_KEY")
        return 2

    path = database_path()
    with connect(path) as con:
        districts = [json.loads(row[0]) for row in con.execute("SELECT payload FROM districts")]

    official = [d for d in districts
                if d.get("kind") == "business_area" and (d.get("center") or {}).get("lng")]
    by_name = {d.get("name"): d for d in districts if d.get("kind") in
               ("district", "county_city", "city")}

    pois: list[dict] = []
    for city in CITIES:
        for keyword in KEYWORDS:
            for page in (1, 2):
                try:
                    batch = fetch(keyword, city, page)
                except Exception as error:
                    print(f"  抓取失败 {city}/{keyword}/p{page}: {error}")
                    break
                time.sleep(0.45)
                for poi in batch:
                    location = (poi.get("location") or "").split(",")
                    if len(location) != 2:
                        continue
                    pois.append({
                        "name": poi.get("name"), "adname": poi.get("adname"),
                        "address": poi.get("address"), "type": poi.get("type"),
                        "keyword": keyword, "source": "amap-place-text",
                        "lng": float(location[0]), "lat": float(location[1]),
                        "id": poi.get("id"),
                    })
                if len(batch) < 25:
                    break
    print(f"  抓到 POI {len(pois)} 条（{len(CITIES) * len(KEYWORDS)} 组关键词）")

    # 贪心聚类：按 name 去重后，逐条并入 800 m 内的已有簇
    seen_names = set()
    clusters: list[dict] = []
    for poi in pois:
        if poi["id"] in seen_names:
            continue
        seen_names.add(poi["id"])
        placed = False
        for cluster in clusters:
            if haversine(poi["lng"], poi["lat"], cluster["lng"], cluster["lat"]) <= CLUSTER_RADIUS:
                cluster["members"].append(poi)
                count = len(cluster["members"])
                cluster["lng"] = (cluster["lng"] * (count - 1) + poi["lng"]) / count
                cluster["lat"] = (cluster["lat"] * (count - 1) + poi["lat"]) / count
                placed = True
                break
        if not placed:
            clusters.append({"lng": poi["lng"], "lat": poi["lat"], "members": [poi]})

    kept = []
    for cluster in clusters:
        if len(cluster["members"]) < MIN_MEMBERS:
            continue
        if any(haversine(cluster["lng"], cluster["lat"], area["center"]["lng"],
                         area["center"]["lat"]) < OFFICIAL_GAP for area in official):
            continue
        # 命名：成员里出现次数最多的 POI 名（去掉"店/分店"后缀）
        names = [m["name"] for m in cluster["members"] if m["name"]]
        dominant = max(set(names), key=names.count) if names else "未命名"
        parent_name = next((m["adname"] for m in cluster["members"] if m["adname"]), "")
        kept.append({
            "name": dominant, "parentName": parent_name,
            "lng": cluster["lng"], "lat": cluster["lat"],
            "members": cluster["members"],
        })
    kept.sort(key=lambda item: -len(item["members"]))
    kept = kept[:MAX_CANDIDATES]
    print(f"  聚类得到 {len(clusters)} 簇，过滤后保留候选 {len(kept)} 个（成员≥{MIN_MEMBERS}，"
          f"距官方中心≥{OFFICIAL_GAP}m）")

    if args.apply:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        backup = path.parent / "backups" / f"menduner-before-candidate-areas-{stamp}.sqlite3"
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup)
        print(f"  备份: {backup} ({backup.stat().st_size // 1048576} MB)")

    written = []
    for index, cluster in enumerate(kept, start=1):
        area_id = f"area-poi-{index:02d}"
        parent = by_name.get(cluster["parentName"])
        payload = {
            "id": area_id,
            "name": f"{cluster['name']}周边",
            "kind": "business_area",
            "status": "candidate",
            "parentId": (parent or {}).get("id"),
            "adminCode": (parent or {}).get("adminCode"),
            "businessAreas": [],
            "center": {
                "lng": round(cluster["lng"], 6), "lat": round(cluster["lat"], 6),
                "system": "GCJ-02", "source": "amap-poi-cluster",
                "matchedName": cluster["name"], "adname": cluster["parentName"],
                "matchLevel": "candidate",
                "matchedAt": datetime.now(timezone.utc).isoformat(),
                "radiusMeters": CLUSTER_RADIUS,
                "algorithm": {
                    "method": "greedy-centroid", "clusterRadiusMeters": CLUSTER_RADIUS,
                    "minMembers": MIN_MEMBERS, "officialGapMeters": OFFICIAL_GAP,
                    "memberCount": len(cluster["members"]),
                    "keywords": sorted({m["keyword"] for m in cluster["members"]}),
                },
                "note": "候选商业集聚点：由 POI 聚类得到，未经政府或地图方确认为正式商圈",
            },
            "members": [
                {"name": m["name"], "address": m["address"], "adname": m["adname"],
                 "type": m["type"], "lng": m["lng"], "lat": m["lat"]}
                for m in cluster["members"][:8]
            ],
        }
        written.append(payload)
        if args.apply:
            with connect(path) as con:
                con.execute(
                    "INSERT INTO districts(id,payload) VALUES(?,?) "
                    "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
                    (area_id, json.dumps(payload, ensure_ascii=False)),
                )

    for row in written[:12]:
        print(f"  + {row['name']}（{row['center']['adname'] or '行政区未知'}，"
              f"{row['center']['algorithm']['memberCount']} 个 POI）")
    print(f"\n  写入候选中心 {len(written)} 个" if args.apply else f"\n  dry-run：将写入 {len(written)} 个")

    if args.apply:
        report = path.parent / "backups" / f"candidate-areas-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.json"
        report.write_text(json.dumps(written, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  报告: {report}")
        with connect(path) as con:
            print("  完整性:", con.execute("PRAGMA integrity_check").fetchone()[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
