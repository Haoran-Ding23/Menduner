"""为有坐标的场馆取行政区归属（高德逆地理编码），先只报告不写库。

行政区是客观事实：一个场馆在姑苏区还是在太仓市，不取决于我们的推断，而是行政区划。
这与"商圈"不同 —— 商圈是从地理推算出来的，行政区可以从权威接口取到并复验。

高德 regeo 返回 cityname 与 adname，对苏州的县级市（太仓/昆山/常熟/张家港）返回
adname=市名；对市辖区返回 adname=区名。先看实际返回，再决定数据模型。
"""
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.database import connect

KEY = os.environ.get("AMAP_WEBSERVICE_KEY")
if not KEY:
    env = ROOT / "frontend/.env.local"
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("AMAP_WEBSERVICE_KEY="):
            KEY = line.split("=", 1)[1].strip()
if not KEY:
    print("没有 AMAP_WEBSERVICE_KEY")
    sys.exit(1)

DB = Path(os.environ.get(
    "MENDUNER_DB_PATH",
    "/srv/menduner/data/menduner.sqlite3" if Path("/srv/menduner/data/menduner.sqlite3").exists()
    else ROOT / "backend" / "data" / "menduner.sqlite3",
))

C = httpx.Client(timeout=20)

with connect(DB) as con:
    rows = [(r["id"], json.loads(r["payload"])) for r in con.execute("SELECT id, payload FROM venues")]

with_coords = [(vid, p) for vid, p in rows if (p.get("coordinates") or {}).get("lng") is not None]
print(f"库: {DB}")
print(f"场馆 {len(rows)}，有坐标 {len(with_coords)}")
print()

out = []
errors = 0
for i, (vid, p) in enumerate(with_coords, 1):
    co = p["coordinates"]
    try:
        r = C.get("https://restapi.amap.com/v3/geocode/regeo", params={
            "key": KEY,
            "location": f"{co['lng']},{co['lat']}",
            "extensions": "base",
        })
        doc = r.json()
        comp = (doc.get("regeocode") or {}).get("addressComponent") or {}
        info = {
            "venue_id": vid,
            "name": p.get("name"),
            "lng": co["lng"], "lat": co["lat"],
            "province": comp.get("province"),
            "city": comp.get("city") or None,
            "district": comp.get("district") or None,
            "township": comp.get("township") or None,
            "citycode": comp.get("citycode"),
            "adcode": comp.get("adcode"),
        }
    except Exception as exc:
        errors += 1
        print(f"  [{i:2d}] {p.get('name')}  失败 {type(exc).__name__}")
        continue
    out.append(info)
    print(f"  [{i:2d}] {str(info['name'])[:30]:32s} 市={info['city']} 区={info['district']} 街道={info['township']}")
    time.sleep(0.12)

print()
print(f"成功 {len(out)}，失败 {errors}")
print()
print("=== 行政区取值分布 ===")
for key in ("city", "district"):
    c = Counter(x[key] for x in out)
    print(f"  {key}:")
    for k, v in c.most_common():
        print(f"      {str(k):14s} {v}")

Path("region_lookup.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print()
print("已写出 region_lookup.json")
