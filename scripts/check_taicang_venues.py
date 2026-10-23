"""查太仓文化馆/大剧院、以及太仓商场类场馆，在我们库里有没有活动。"""
import json
import sqlite3
from pathlib import Path

con = sqlite3.connect(Path("/srv/menduner/data/menduner.sqlite3"))
con.row_factory = sqlite3.Row

venues = {r["id"]: json.loads(r["payload"]) for r in con.execute("SELECT id, payload FROM venues")}
events = list(con.execute("SELECT id, name, startDate, endDate, venue, district, source FROM events"))

KEY_VENUES = ["太仓市文化馆", "太仓大剧院", "文化馆", "大剧院", "万达", "吾悦", "宝龙", "金鹰", "印象城",
              "商场", "广场", "购物", "茂", "百货", "中心"]


def venue_name(vid):
    return (venues.get(vid or "") or {}).get("name") or ""


print("=== 1. 太仓的场馆（含文化馆/大剧院/商场类）===")
taicang_venues = [(vid, v) for vid, v in venues.items()
                  if "太仓" in (v.get("name") or "") or "浏河" in (v.get("name") or "")]
print(f"  名称含太仓/浏河的场馆: {len(taicang_venues)} 个")
for vid, v in taicang_venues:
    count = sum(1 for e in events if e["venue"] == vid)
    print(f"    {v.get('name'):28s} 活动 {count}")

print()
print("=== 2. 名称含文化馆/大剧院/商场关键词的场馆（全库）===")
for vid, v in venues.items():
    name = v.get("name") or ""
    if any(k in name for k in ("文化馆", "大剧院", "万达", "吾悦", "宝龙", "金鹰", "印象城", "茂", "百货")):
        count = sum(1 for e in events if e["venue"] == vid)
        print(f"    {name:30s} 活动 {count}  id={vid}")

print()
print("=== 3. 名称含这些关键词的活动（全库）===")
for e in events:
    if any(k in (e["name"] or "") for k in ("万达", "吾悦", "宝龙", "金鹰", "商场", "购物中心")):
        print(f"    {e['startDate']}  {e['name'][:44]}  来源={e['source']}")

print()
print("=== 4. 太仓活动的场馆分布 ===")
from collections import Counter
taicang_events = [e for e in events if e["district"] == "taicang"]
print(f"  太仓活动 {len(taicang_events)} 条")
for name, n in Counter(venue_name(e["venue"]) or "(无场馆)" for e in taicang_events).most_common(12):
    print(f"    {name:30s} {n}")
