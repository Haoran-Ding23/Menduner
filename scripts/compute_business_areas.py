"""Give each business area a centre, then assign hotels to one by distance.

## Why this exists

The system held 20 business areas from AMap's reverse geocoding but only their names: no
centre, no extent. So a hotel could only be placed in a district by hand - 7 of 15 were, 8
were never done - and nothing could draw a business area on the map.

## What counts as a business area

高德 gives a 商圈 as a NAMED POINT, not a boundary. So a centre is looked up from the name and
the extent has to be computed, which means the extent is ours. Two consequences are handled
honestly:

  * the centre is a fact (AMap returned it) and is stored with its source URL;
  * the assignment is a computation, so it is recorded as ``Computed`` rather than
    ``Verified`` - a human has not confirmed that this hotel belongs to this business area,
    a distance rule has. The distance and the threshold travel with the record so anyone can
    re-check the call.

## The assignment rule

Nearest centre wins, but only within a threshold. Beyond it the hotel is LEFT UNASSIGNED and
recorded as ``OutOfRange`` instead of being pushed into a business area it is nowhere near:
``太仓`` is one business area covering a whole county-level city, and a hotel 12 km from its
centre is not in it.

Run with --apply to write; without it, the script only reports.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from datetime import datetime, timezone
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
REVIEWER = "menduner-lead"
# 3 km is roughly the walkable core of a 商圈. It is a judgement, so it is written into every
# record rather than left implicit; widening it changes the answer and must be visible.
ASSIGN_RADIUS_KM = 3.0

KEY = os.environ.get("AMAP_WEBSERVICE_KEY")
if not KEY:
    env = ROOT / "frontend/.env.local"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("AMAP_WEBSERVICE_KEY="):
                KEY = line.split("=", 1)[1].strip()

ap = argparse.ArgumentParser()
ap.add_argument("--db", type=Path, default=DB)
ap.add_argument("--radius-km", type=float, default=ASSIGN_RADIUS_KM)
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

C = httpx.Client(timeout=25)


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    r = 6371.0
    la1, lo1, la2, lo2 = map(math.radians, (a[1], a[0], b[1], b[0]))
    dla, dlo = la2 - la1, lo2 - lo1
    h = math.sin(dla / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlo / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def lookup_centre(name: str) -> tuple[float, float] | None:
    """The business area's representative point, from its own name.

    A 商圈 has no boundary in AMap, but it does exist as a POI whose name is the business
    area's name, and that POI carries a location. Reusing AMap's own point keeps the fact where
    it belongs instead of inventing a centroid from our hotel positions.
    """
    for attempt in range(4):
        try:
            r = C.get("https://restapi.amap.com/v3/place/text", params={
                "key": KEY, "keywords": name, "city": "苏州", "offset": 10, "page": 1})
            doc = r.json()
            if str(doc.get("status")) != "1":
                time.sleep(1.0 * (attempt + 1))
                continue
            for poi in doc.get("pois") or []:
                if (poi.get("name") or "").strip() == name:
                    lng, lat = (float(x) for x in poi["location"].split(","))
                    return lng, lat
            return None
        except Exception:
            time.sleep(0.8)
    return None


with connect(args.db) as con:
    districts = {r["id"]: json.loads(r["payload"])
                 for r in con.execute("SELECT id, payload FROM districts")}
    hotels = [(r["id"], json.loads(r["payload"]))
              for r in con.execute("SELECT id, payload FROM hotels")]

areas = [(did, p) for did, p in districts.items() if p.get("kind") == "business_area"]
print(f"库: {args.db}")
print(f"商圈 {len(areas)} 个，酒店 {len(hotels)} 个")
print()

centres: dict[str, dict] = {}
for did, payload in areas:
    name = payload.get("name") or ""
    co = payload.get("coordinates")
    if co and co.get("lng") is not None:
        centres[did] = {"name": name, "lng": co["lng"], "lat": co["lat"],
                        "sourceUrl": co.get("sourceUrl")}
        print(f"  {name:10s} 已有中心点 {co['lng']:.6f},{co['lat']:.6f}")
        continue
    if not KEY:
        print(f"  {name:10s} 没有 AMAP_WEBSERVICE_KEY，跳过")
        continue
    found = lookup_centre(name)
    if found:
        centres[did] = {"name": name, "lng": found[0], "lat": found[1], "sourceUrl": None}
        print(f"  {name:10s} 查到中心点 {found[0]:.6f},{found[1]:.6f}")
    else:
        print(f"  {name:10s} 查不到中心点")
    time.sleep(0.4)

print()
print(f"=== 中心点就绪: {len(centres)} 个 ===")
print()
print(f"=== 酒店归属（半径 {args.radius_km} km）===")
assign: list[dict] = []
out_of_range: list[dict] = []
for hid, payload in hotels:
    co = payload.get("coordinates") or {}
    if co.get("lng") is None:
        continue
    point = (co["lng"], co["lat"])
    best = None
    for did, centre in centres.items():
        d = haversine_km(point, (centre["lng"], centre["lat"]))
        if best is None or d < best["distance"]:
            best = {"districtId": did, "name": centre["name"], "distance": d}
    if best is None:
        continue
    item = {"hotel_id": hid, "hotel": payload.get("name"), **best}
    if best["distance"] <= args.radius_km:
        assign.append(item)
        print(f"  ✓ {str(payload.get('name'))[:24]:26s} → {best['name']:10s} {best['distance']:.2f} km")
    else:
        out_of_range.append(item)
        print(f"  · {str(payload.get('name'))[:24]:26s} 最近 = {best['name']}({best['distance']:.1f} km) 超出半径，不归属")

print()
print(f"可归属 {len(assign)}，超出半径 {len(out_of_range)}")

if not args.apply:
    print()
    print("  DRY RUN：未写入。加 --apply 执行")
    sys.exit(0)

print()
print("=== 写入 ===")
now = datetime.now(timezone.utc).isoformat()
with connect(args.db) as con:
    for did, centre in centres.items():
        payload = districts[did]
        payload["coordinates"] = {
            "lng": centre["lng"],
            "lat": centre["lat"],
            "system": "GCJ-02",
            "status": "Verified" if centre.get("sourceUrl") else "Computed",
            "sourceUrl": centre.get("sourceUrl")
            or f"https://ditu.amap.com/search?query={centre['name']}",
        }
        con.execute("UPDATE districts SET payload=? WHERE id=?",
                    (json.dumps(payload, ensure_ascii=False, sort_keys=True), did))
    print(f"  商圈中心点 {len(centres)} 个")

    for item in assign + out_of_range:
        row = con.execute("SELECT payload FROM hotels WHERE id=?", (item["hotel_id"],)).fetchone()
        payload = json.loads(row["payload"])
        payload["businessArea"] = {
            "districtId": item["districtId"] if item in assign else None,
            "name": item["name"],
            "distanceKm": round(item["distance"], 3),
            "thresholdKm": args.radius_km,
            "status": "Computed" if item in assign else "OutOfRange",
            "computedAt": now,
            "computedBy": REVIEWER,
            # The rule, stated in full, so the number can be judged without reading this file.
            "rule": (f"nearest business-area centre within {args.radius_km} km; "
                     "centres from AMap POI lookup"),
        }
        if item in assign:
            payload["districtId"] = item["districtId"]
        con.execute("UPDATE hotels SET payload=? WHERE id=?",
                    (json.dumps(payload, ensure_ascii=False, sort_keys=True), item["hotel_id"]))
    print(f"  酒店归属 {len(assign)} 个，记为「计算得出」")
    print(f"  超出半径 {len(out_of_range)} 个，记为「不在任何商圈范围内」")

print()
print("=== 复核 ===")
with connect(args.db) as con:
    rows = [json.loads(r[0]) for r in con.execute("SELECT payload FROM hotels")]
    named = sum(1 for p in rows if p.get("businessArea", {}).get("status") == "Computed")
    out = sum(1 for p in rows if p.get("businessArea", {}).get("status") == "OutOfRange")
    print(f"  酒店 {len(rows)}：已归属 {named}，超范围 {out}，未处理 {len(rows) - named - out}")
    print(f"  integrity: {con.execute('PRAGMA integrity_check').fetchone()[0]}")
    print(f"  foreign_key: {len(con.execute('PRAGMA foreign_key_check').fetchall())} 个问题")
