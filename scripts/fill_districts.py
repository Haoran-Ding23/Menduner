"""Fill in the administrative regions for Suzhou and assign every venue to one.

## Why administrative regions and not business districts

The map needs a way in: a hotel in 太仓 cares about 太仓 first, and only then about the rest
of Suzhou. That requires every venue to belong to exactly one region, and the region to be a
fact rather than an inference.

An administrative division is that fact. 太仓市 and 姑苏区 are defined by the state and
published by AMap's reverse-geocoding endpoint, which is queried here. A business district
(湖东, 观前) is a commercial notion that would have to be inferred, and the project already
records why it does not want to infer those. This distinction is the reason the previous
``districtId`` column stayed empty: nobody had decided which of the two it meant.

## The hierarchy

    苏州市
      ├── 姑苏区   虎丘区   吴中区   相城区   吴江区      (市辖区)
      └── 常熟市   张家港市  昆山市   太仓市              (代管县级市)

苏州工业园区 is deliberately NOT a region here. It is a functional development zone, not an
administrative division, and AMap places its venues in 吴中区 - which is where they legally
are. Adding it as a pseudo-region would make the list of regions contradict the authority it
claims to come from. The township (金鸡湖街道) is stored alongside, so the finer geography is
not lost, and a reader who knows Suzhou can see why 吴中区 holds so many venues.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.database import connect

DB = Path(os.environ.get(
    "MENDUNER_DB_PATH",
    "/srv/menduner/data/menduner.sqlite3" if Path("/srv/menduner/data/menduner.sqlite3").exists()
    else ROOT / "backend" / "data" / "menduner.sqlite3",
))

# The regions a hotel would browse. Ordered as they are discovered, but display order is the
# UI's business; identity is what matters here.
REGIONS = [
    ("suzhou", "苏州市", "city", None),
    ("gusu", "姑苏区", "district", "suzhou"),
    ("huqiu", "虎丘区", "district", "suzhou"),
    ("wuzhong", "吴中区", "district", "suzhou"),
    ("xiangcheng", "相城区", "district", "suzhou"),
    ("wujiang", "吴江区", "district", "suzhou"),
    ("changshu", "常熟市", "county_city", "suzhou"),
    ("zhangjiagang", "张家港市", "county_city", "suzhou"),
    ("kunshan", "昆山市", "county_city", "suzhou"),
    ("taicang", "太仓市", "county_city", "suzhou"),
]

# AMap's adname -> our region id. A name missing from here is reported rather than guessed.
NAME_TO_ID = {name: rid for rid, name, _kind, _parent in REGIONS}

KEY = os.environ.get("AMAP_WEBSERVICE_KEY")
if not KEY:
    env = ROOT / "frontend/.env.local"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("AMAP_WEBSERVICE_KEY="):
                KEY = line.split("=", 1)[1].strip()

ap = argparse.ArgumentParser()
ap.add_argument("--db", type=Path, default=DB)
ap.add_argument("--apply", action="store_true")
ap.add_argument("--reuse", type=Path, default=None,
                help="reuse a previous region_lookup.json instead of calling AMap again")
args = ap.parse_args()

C = httpx.Client(timeout=25)


def regeo(lng: float, lat: float) -> dict:
    """Reverse geocode one point, retrying the transient failures.

    AMap answers HTTP 200 with status "0" and an empty object when it is rate limiting, so a
    plain request loop silently records blanks. The first run lost 9 of 89 venues this way;
    the retry is what turns that into zero, not a change of coordinates.
    """
    last = ""
    for attempt in range(5):
        try:
            r = C.get("https://restapi.amap.com/v3/geocode/regeo", params={
                "key": KEY, "location": f"{lng},{lat}", "extensions": "base"})
            doc = r.json()
            if str(doc.get("status")) == "1":
                comp = (doc.get("regeocode") or {}).get("addressComponent") or {}
                return {
                    "city": comp.get("city") or None,
                    "district": comp.get("district") or None,
                    "township": comp.get("township") or None,
                    "adcode": comp.get("adcode") or None,
                }
            last = str(doc.get("info"))
            if "LIMIT" in last.upper() or "QPS" in last.upper():
                time.sleep(1.2 * (attempt + 1))
                continue
            time.sleep(0.4)
        except Exception as exc:  # network hiccup
            last = type(exc).__name__
            time.sleep(0.6)
    return {"city": None, "district": None, "township": None,
            "adcode": None, "error": last or "unknown"}


with connect(args.db) as con:
    venue_rows = [(r["id"], json.loads(r["payload"]))
                  for r in con.execute("SELECT id, payload FROM venues")]

with_coords = [(vid, p) for vid, p in venue_rows
               if (p.get("coordinates") or {}).get("lng") is not None]

cached = {}
if args.reuse and args.reuse.exists():
    for item in json.loads(args.reuse.read_text(encoding="utf-8")):
        if item.get("district"):
            cached[item["venue_id"]] = item
    print(f"复用已有结果: {len(cached)} 个")

print(f"库: {args.db}")
print(f"场馆 {len(venue_rows)}，有坐标 {len(with_coords)}")
print()

# venue_id -> region id
assign: dict[str, dict] = {}
unknown: list[str] = []
resolved_n = 0
for i, (vid, p) in enumerate(with_coords, 1):
    co = p["coordinates"]
    if vid in cached:
        info = cached[vid]
        resolved_n += 1
    else:
        info = regeo(co["lng"], co["lat"])
        if info.get("district"):
            resolved_n += 1
        time.sleep(0.55)  # stay well under the free-tier QPS limit
    district_name = info.get("district")
    region_id = NAME_TO_ID.get(district_name) if district_name else None
    if region_id is None:
        unknown.append(f"{p.get('name')}（{district_name or info.get('error') or '无返回值'}）")
        continue
    assign[vid] = {
        "region": region_id,
        "district_name": district_name,
        "township": info.get("township"),
        "city": info.get("city"),
    }
    if i % 15 == 0:
        print(f"  ...已处理 {i}/{len(with_coords)}")

print(f"  取到行政区: {resolved_n} / {len(with_coords)}")
print(f"  归入已知地区: {len(assign)}")
if unknown:
    print(f"  未归入（{len(unknown)}）:")
    for line in unknown:
        print(f"      {line}")
print()

# Event -> venue -> region. An event with no venue has no region, and that is reported.
with connect(args.db) as con:
    events = [(r["id"], r["venue"], r["name"]) for r in
              con.execute("SELECT id, venue, name FROM events")]
event_assign = [(eid, assign[v]["region"]) for eid, v, _n in events if v in assign]
no_venue = sum(1 for _eid, v, _n in events if not v)
no_region = sum(1 for _eid, v, _n in events if v and v not in assign)

print(f"活动 {len(events)}：可归属地区 {len(event_assign)}，无场馆 {no_venue}，场馆无地区 {no_region}")
print()
print("=== 地区汇总 ===")
from collections import Counter
c = Counter(region for _eid, region in event_assign)
vc = Counter(info["region"] for info in assign.values())
for rid, name, kind, _parent in REGIONS:
    if rid == "suzhou":
        continue
    print(f"  {name:8s} ({kind:11s})  场馆 {vc.get(rid, 0):2d}  活动 {c.get(rid, 0):3d}")

if not args.apply:
    print()
    print("  DRY RUN：未写入。加 --apply 执行")
    sys.exit(0)

print()
print("=== 写入 ===")
with connect(args.db) as con:
    con.execute("CREATE TABLE IF NOT EXISTS districts (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
    for rid, name, kind, parent in REGIONS:
        payload = {
            "id": rid,
            "name": name,
            "kind": kind,
            "parentId": parent,
            "level": 0 if rid == "suzhou" else 1,
            "demo": False,
            # Says where the fact came from, so the region list never floats free of a source.
            "source": "administrative division; assigned by AMap reverse geocoding (adname)",
        }
        con.execute(
            "INSERT INTO districts(id, payload) VALUES(?,?) "
            "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
            (rid, json.dumps(payload, ensure_ascii=False, sort_keys=True)),
        )
    print(f"  地区 {len(REGIONS)} 个")
    for vid, info in assign.items():
        row = con.execute("SELECT payload FROM venues WHERE id=?", (vid,)).fetchone()
        payload = json.loads(row["payload"])
        payload["districtId"] = info["region"]
        # The township is kept because it is the finest authoritative location we have, and
        # because it explains why 吴中区 holds the 工业园区 venues.
        if info.get("township"):
            payload["township"] = info["township"]
        con.execute("UPDATE venues SET payload=? WHERE id=?",
                    (json.dumps(payload, ensure_ascii=False, sort_keys=True), vid))
    print(f"  场馆归属 {len(assign)} 个")
    for eid, region in event_assign:
        con.execute("UPDATE events SET district=? WHERE id=?", (region, eid))
    print(f"  活动归属 {len(event_assign)} 个")

print()
print("=== 复核 ===")
with connect(args.db) as con:
    print(f"  districts 行数: {con.execute('SELECT COUNT(*) FROM districts').fetchone()[0]}")
    print(f"  有 district 的活动: "
          f"{con.execute('SELECT COUNT(*) FROM events WHERE district IS NOT NULL').fetchone()[0]}"
          f" / {con.execute('SELECT COUNT(*) FROM events').fetchone()[0]}")
    print(f"  integrity: {con.execute('PRAGMA integrity_check').fetchone()[0]}")
    print(f"  foreign_key: {len(con.execute('PRAGMA foreign_key_check').fetchall())} 个问题")
