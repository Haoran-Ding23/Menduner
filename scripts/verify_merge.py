"""合并后核对：坐标是否保留、活动数是否不变。"""
import json
import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = Path(os.environ.get(
    "MENDUNER_DB_PATH",
    "/srv/menduner/data/menduner.sqlite3" if Path("/srv/menduner/data/menduner.sqlite3").exists()
    else ROOT / "backend" / "data" / "menduner.sqlite3",
))

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

rows = []
for r in con.execute("SELECT id, payload FROM venues"):
    p = json.loads(r["payload"])
    rows.append((r["id"], p))

print(f"库: {DB}")
print(f"场馆数: {len(rows)}")
print(f"活动数: {con.execute('SELECT COUNT(*) FROM events').fetchone()[0]}")

for label, needle in (("狮山", "狮山"), ("开明", "开明"), ("奥体", "奥体"), ("金鸡湖音乐厅", "金鸡湖音乐厅")):
    print()
    print(f"=== 名称含「{needle}」的场馆 ===")
    for vid, p in rows:
        if needle not in str(p.get("name") or ""):
            continue
        n = con.execute("SELECT COUNT(*) FROM events WHERE venue=?", (vid,)).fetchone()[0]
        coord = p.get("coordinates")
        flag = "有" if coord else "无"
        print(f"  {str(p.get('name'))[:34]:36s} 活动 {n:3d}  坐标 {flag}  地址 {str(p.get('address'))[:30]}")

# 别名文件
alias_like = ROOT / "crawler" / "venue_aliases.json"
if alias_like.exists():
    doc = json.loads(alias_like.read_text(encoding="utf-8"))
    print()
    print(f"=== 别名文件：{len(doc.get('aliases', []))} 条 ===")
    for a in doc.get("aliases", []):
        print(f"  {str(a.get('alias_name'))[:36]:38s} -> {a.get('canonical_id')}")
