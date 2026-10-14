"""Report the future-event picture under the frontend's default filter window.

The frontend defaults to year=2026, month=10 (usePlatform filters).
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

DB = Path(sys.argv[1] if len(sys.argv) > 1 else "backend/data/menduner.sqlite3")
TODAY = date(2026, 10, 13)

con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
con.row_factory = sqlite3.Row

rows = list(con.execute(
    "SELECT id, name, category, startDate, endDate, venue, source, verification_status "
    "FROM events ORDER BY startDate"))

print(f"today = {TODAY}\n")
past, future = [], []
for r in rows:
    sd = date.fromisoformat(r["startDate"]) if r["startDate"] else None
    (future if sd and sd >= TODAY else past).append((r, sd))

print(f"== FUTURE events ({len(future)}) ==")
for r, sd in future:
    print(f"  {sd}  [{r['category']:8s}] {r['name'][:50]}")
    print(f"        source={r['source']}")

print(f"\n== PAST/historical events retained as observations ({len(past)}) ==")
for r, sd in past:
    print(f"  {sd}  [{r['category']:8s}] {r['name'][:50]}")

print("\n== frontend default window (year=2026, month=10) ==")
in_window = [r for r, sd in future + past
             if sd and sd.year == 2026 and sd.month == 10]
print(f"  visible by default: {len(in_window)}")
for r in in_window:
    print(f"    {r['startDate']} {r['name'][:50]}")

print("\n== sources actually producing events ==")
for r in con.execute(
        "SELECT source, COUNT(*) c FROM events GROUP BY source ORDER BY c DESC"):
    print(f"  {r['source']:36s} {r['c']}")

print("\n== venue payload completeness (map/venue pages need these) ==")
venues = {r["id"]: json.loads(r["payload"]) for r in con.execute("SELECT id,payload FROM venues")}
for vid, payload in venues.items():
    used = con.execute("SELECT COUNT(*) FROM events WHERE venue=?", (vid,)).fetchone()[0]
    if used == 0:
        continue
    has_coords = bool(payload.get("coordinates"))
    print(f"  {vid[:34]:34s} events={used} name={str(payload.get('name'))[:28]:28s} "
          f"coords={'yes' if has_coords else 'NO '} district={payload.get('districtId')}")

print("\n== hotels / districts available for Hotel Intelligence + District pages ==")
print("  hotels   :", [json.loads(r['payload']).get('name') for r in con.execute("SELECT payload FROM hotels")])
print("  districts:", [json.loads(r['payload']).get('name') for r in con.execute("SELECT payload FROM districts")])

print("\n== evidence freshness ==")
for r in con.execute("""SELECT COUNT(DISTINCT event_id) events, COUNT(*) rows FROM crawler_evidence"""):
    print(f"  crawler_evidence: {r['rows']} rows across {r['events']} events")
con.close()
