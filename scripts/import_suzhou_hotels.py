"""把酒店数据补到整个苏州（含太仓、昆山、常熟、张家港），用于商圈「已收录酒店」内容。

规则与太仓版一致（不猜、不编）：
  * 只用高德 POI 公开信息（place/text，types=住宿服务，citylimit）；
  * 品牌只在酒店名以品牌 token 开头时才算（不做模糊匹配）；
  * 星级只取 POI 类型串里明确写的「五星级/四星级/三星级」，其余标未标注；
  * 坐标系统一 GCJ-02，status=Verified（高德 POI 自带地址与坐标）；
  * 按 hotel-amap-<poiid> 幂等写入，重复执行不产生重复记录；
  * 写入前备份整库。

用法：
  python scripts/import_suzhou_hotels.py --dry-run
  python scripts/import_suzhou_hotels.py --apply --pages 4
"""
from __future__ import annotations

import argparse
import json
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
CITIES = ["苏州", "太仓", "昆山", "常熟", "张家港"]
BRANDS = ["洲际", "万豪", "希尔顿", "喜来登", "凯悦", "香格里拉", "雅高", "皇冠假日",
          "亚朵", "全季", "桔子", "汉庭", "如家", "锦江", "维也纳", "麗枫", "希尔顿欢朋"]
STAR_TOKENS = {"五星级": "五星级", "四星级": "四星级", "三星级": "三星级"}


def search(city: str, page: int) -> list[dict]:
    query = urllib.parse.urlencode({
        "key": KEY, "keywords": "酒店", "types": "100000", "city": city,
        "citylimit": "true", "offset": "25", "page": str(page), "extensions": "base",
    })
    with urllib.request.urlopen(f"{ENDPOINT}?{query}", timeout=25) as response:
        return (json.loads(response.read().decode("utf-8")).get("pois") or [])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--pages", type=int, default=3)
    args = parser.parse_args()
    if not args.apply and not args.dry_run:
        args.dry_run = True
    if args.apply and not KEY:
        print("缺少 AMAP_WEBSERVICE_KEY")
        return 2

    path = database_path()
    with connect(path) as con:
        existing = {row[0] for row in con.execute("SELECT id FROM hotels")}
        districts = [json.loads(row[0]) for row in con.execute("SELECT payload FROM districts")]
    by_admin = {d.get("adminCode"): d for d in districts if d.get("adminCode")}
    by_name = {d.get("name"): d for d in districts if d.get("kind") in ("district", "county_city", "city")}

    seen: dict[str, dict] = {}
    for city in CITIES:
        for page in range(1, args.pages + 1):
            try:
                batch = search(city, page)
            except Exception as error:
                print(f"  抓取失败 {city} p{page}: {error}")
                break
            time.sleep(0.45)
            for poi in batch:
                poi_id = poi.get("id")
                location = (poi.get("location") or "").split(",")
                if not poi_id or len(location) != 2 or poi_id in seen:
                    continue
                name = (poi.get("name") or "").strip()
                if not name:
                    continue
                type_text = poi.get("type") or ""
                star = next((label for token, label in STAR_TOKENS.items() if token in type_text), None)
                brand = next((token for token in BRANDS if name.startswith(token)), None)
                adname = poi.get("adname") or ""
                district = by_name.get(adname) or by_admin.get((poi.get("adcode") or "")[:6])
                business = (poi.get("business_area") or "").strip()
                area = next(
                    (d for d in districts
                     if d.get("kind") == "business_area" and business and business in (d.get("name") or "")),
                    None,
                )
                seen[poi_id] = {
                    "poiId": poi_id, "name": name, "city": city,
                    "address": poi.get("address"), "adname": adname,
                    "lng": float(location[0]), "lat": float(location[1]),
                    "type": type_text, "starLabel": star, "brand": brand,
                    "businessArea": business,
                    "districtId": (area or district or {}).get("id"),
                    "dish": poi.get("tag") or "",
                }
            if len(batch) < 25:
                break
    print(f"  抓到酒店 POI {len(seen)} 条（{len(CITIES)} 个城市 × {args.pages} 页）")
    fresh = [row for key, row in seen.items() if f"hotel-amap-{key}" not in existing]
    print(f"  其中新增 {len(fresh)} 条")
    if not fresh:
        print("  没有新增，结束")
        return 0

    if args.apply:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        backup = path.parent / "backups" / f"menduner-before-suzhou-hotels-{stamp}.sqlite3"
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup)
        print(f"  备份: {backup} ({backup.stat().st_size // 1048576} MB)")

    written = 0
    for row in fresh:
        payload = {
            "id": f"hotel-amap-{row['poiId']}",
            "name": row["name"],
            "brand": row["brand"],
            "starLabel": row["starLabel"],
            "districtId": row["districtId"],
            "address": row["address"],
            "demo": False,
            "coordinates": {
                "lng": row["lng"], "lat": row["lat"], "system": "GCJ-02", "status": "Verified",
                "sourceUrl": f"https://uri.amap.com/marker?position={row['lng']},{row['lat']}",
            },
            "source": "amap-place-text",
            "note": "高德 POI 公开信息（住宿服务类目）；星级取自 POI 类型串，未标注则为空",
        }
        if args.apply:
            with connect(path) as con:
                con.execute("INSERT OR REPLACE INTO hotels(id,payload) VALUES(?,?)",
                            (payload["id"], json.dumps(payload, ensure_ascii=False)))
            written += 1

    if args.apply:
        with connect(path) as con:
            total = con.execute("SELECT COUNT(*) FROM hotels").fetchone()[0]
            with_coords = con.execute(
                "SELECT COUNT(*) FROM hotels WHERE payload LIKE '%\"lng\"%'").fetchone()[0]
            print(f"  写入 {written} 条；酒店总数 {total}（其中带坐标 {with_coords}）")
            print("  完整性:", con.execute("PRAGMA integrity_check").fetchone()[0])
        report = path.parent / "backups" / f"suzhou-hotels-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.json"
        report.write_text(json.dumps(fresh, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  报告: {report}")
    else:
        for row in fresh[:10]:
            print(f"   + {row['name']}（{row['adname']}，{row['starLabel'] or '星级未标注'}，"
                  f"商圈 {row['businessArea'] or '无'}）")
        print(f"  dry-run：将写入 {len(fresh)} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
