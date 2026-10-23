"""修正：娄东宾馆匹配到的 POI 是「项目部」，坐标降级为待复核，不冒充已核验。"""
import json
import sqlite3
from pathlib import Path

DB = Path("/srv/menduner/data/menduner.sqlite3")
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

row = None
for r in con.execute("SELECT id, payload FROM hotels"):
    payload = json.loads(r["payload"])
    if payload.get("name") == "太仓市娄东宾馆":
        row = r
        break

if row is None:
    print("  未找到娄东宾馆")
else:
    payload = json.loads(row["payload"])
    coord = payload.get("coordinates") or {}
    print(f"  修正前: {coord.get('status')}  sourceUrl={coord.get('sourceUrl')}")
    coord["status"] = "Needs Review"
    coord["reviewNote"] = "高德匹配到「娄东宾馆项目部」，疑似施工项目点而非宾馆，坐标需人工确认"
    payload["coordinates"] = coord
    con.execute("UPDATE hotels SET payload=? WHERE id=?",
                (json.dumps(payload, ensure_ascii=False), row["id"]))
    con.commit()
    print(f"  修正后: {coord['status']}  note={coord['reviewNote']}")
