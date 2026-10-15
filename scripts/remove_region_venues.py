"""移除「区域名当场馆」的坏行。

只处理一个明确的对象：场馆名是纯行政区名（如 太仓市），且它承载的是全市范围活动。

做法：
  1. 把这些行的活动改为 venue = NULL（保留活动自己的 location/地点 声明和 district）
  2. 删除这些场馆行
  3. 记录一条 venue_edits 供追溯

不推断、不猜坐标。dry-run 默认开启。
"""
import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from crawler.venue_duplicates import is_region_name

CANDIDATES = [
    Path(os.environ["MENDUNER_DB_PATH"]) if os.environ.get("MENDUNER_DB_PATH") else None,
    Path("/srv/menduner/data/menduner.sqlite3"),
    ROOT / "backend" / "data" / "menduner.sqlite3",
]
DB = next((p for p in CANDIDATES if p and p.exists()), CANDIDATES[-1])
REVIEWER = "menduner-lead"

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

targets = []
for r in con.execute("SELECT id, payload FROM venues"):
    p = json.loads(r["payload"])
    if is_region_name(p.get("name")):
        n = con.execute("SELECT COUNT(*) FROM events WHERE venue=?", (r["id"],)).fetchone()[0]
        targets.append((r["id"], p.get("name"), n))

print(f"库: {DB}")
print(f"场馆总数: {con.execute('SELECT COUNT(*) FROM venues').fetchone()[0]}")
print()
if not targets:
    print("没有「区域名当场馆」的行")
    sys.exit(0)

print(f"=== 找到 {len(targets)} 个坏行 ===")
for vid, name, n in targets:
    print()
    print(f"  [{name}]  活动 {n} 条  {vid}")
    for e in con.execute("SELECT id, name, startDate, district, payload FROM events WHERE venue=?", (vid,)):
        ep = json.loads(e["payload"])
        print(f"      {e['startDate']}  {e['name'][:56]}")
        print(f"          现有 district={e['district']}  payload.location={str(ep.get('location'))[:50]}")

if not args.apply:
    print()
    print("  DRY RUN：未改动。加 --apply 执行。")
    sys.exit(0)

now = datetime.now(timezone.utc).isoformat()
moved = 0
for vid, name, n in targets:
    for e in con.execute("SELECT id, payload FROM events WHERE venue=?", (vid,)):
        payload = json.loads(e["payload"])
        payload["venueId"] = None
        con.execute(
            "UPDATE events SET venue=NULL, payload=? WHERE id=?",
            (json.dumps(payload, ensure_ascii=False, sort_keys=True), e["id"]),
        )
        con.execute(
            "UPDATE crawler_unified_events SET normalized_json=? WHERE event_id=?",
            (json.dumps(payload, ensure_ascii=False, sort_keys=True), e["id"]),
        )
        moved += 1
    # 观测里的 venue_id 一并清掉
    for row in con.execute("SELECT source_id, item_key, normalized_json FROM crawler_observations"):
        try:
            doc = json.loads(row["normalized_json"])
        except ValueError:
            continue
        if doc.get("venue_id") != vid:
            continue
        doc["venue_id"] = None
        con.execute(
            "UPDATE crawler_observations SET normalized_json=? WHERE source_id=? AND item_key=?",
            (json.dumps(doc, ensure_ascii=False, sort_keys=True), row["source_id"], row["item_key"]),
        )
    con.execute("DELETE FROM venues WHERE id=?", (vid,))
    con.execute(
        "INSERT INTO venue_edits(id, venue_id, kind, detail, reviewer, note, edited_at) "
        "VALUES(?,?,?,?,?,?,?)",
        (f"vedit:{vid}:region_row_removed:{now}",
         vid, "region_row_removed",
         json.dumps({"name": name, "events_unlinked": n}, ensure_ascii=False),
         REVIEWER,
         "场馆名是行政区名，不是场馆：官方文章提取把标题的「单位：」前缀当成场馆，"
         "全市活动的标题前缀就是市名。改为无场馆，事件的地点声明与 district 不动。",
         now),
    )
    print(f"  已移除 [{name}]，{n} 条活动改为无场馆")

con.commit()
print()
print(f"  完成：{len(targets)} 行移除，{moved} 条活动解除场馆关联")
print(f"  场馆总数: {con.execute('SELECT COUNT(*) FROM venues').fetchone()[0]}")
print(f"  活动总数: {con.execute('SELECT COUNT(*) FROM events').fetchone()[0]}")
