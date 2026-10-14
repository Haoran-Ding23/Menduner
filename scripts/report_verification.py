"""Report the outcome of the V1.6.3 auto-verification rule on the production database."""
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import date
from pathlib import Path

DB = Path("backend/data/menduner.sqlite3")
con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
con.row_factory = sqlite3.Row
TODAY = date(2026, 10, 13)

events = list(con.execute("SELECT id, name, startDate, category, source, verification_status FROM events"))
print(f"events total: {len(events)}  future: {sum(1 for e in events if e['startDate'] and date.fromisoformat(e['startDate']) >= TODAY)}")
print()
print("== event-level verification_status ==")
for r in con.execute("SELECT verification_status, COUNT(*) c FROM events GROUP BY verification_status ORDER BY c DESC"):
    print(f"   {r[0]:14s} {r[1]}")
print()
print("== crawler_evidence status ==")
for r in con.execute("SELECT verification_status, COUNT(*) c FROM crawler_evidence GROUP BY verification_status ORDER BY c DESC"):
    print(f"   {r[0]:14s} {r[1]}")
print()
print("== who decided each Verified claim ==")
rows = con.execute("""SELECT e.field_name, e.source, f.payload
                      FROM crawler_evidence e JOIN evidence f ON f.id=e.id
                      WHERE e.verification_status='Verified'""").fetchall()
origin = Counter()
by_field = Counter()
by_source = Counter()
for r in rows:
    p = json.loads(r["payload"])
    origin[p.get("origin") or "?"] += 1
    by_field[r["field_name"]] += 1
    by_source[r["source"]] += 1
print("   by origin:", dict(origin))
print("   by field :", dict(by_field))
print("   by source:", dict(by_source))
print()
print("== per event: verified field count ==")
per = Counter()
for r in con.execute("""SELECT event_id, COUNT(*) c FROM crawler_evidence
                        WHERE verification_status='Verified' GROUP BY event_id"""):
    per[r["c"]] += 1
for k in sorted(per):
    print(f"   {k} verified fields: {per[k]} events")
fully = sum(c for k, c in per.items() if k >= 6)
print(f"   events with >=6 verified fields: {fully} of {len(events)}")
print()
print("== rule reasons for the still-pending rows (top 8) ==")
pend = Counter()
for r in con.execute("""SELECT f.payload FROM crawler_evidence e
                        JOIN evidence f ON f.id=e.id
                        WHERE e.verification_status <> 'Verified'"""):
    p = json.loads(r["payload"])
    o = p.get("origin") or p.get("status") or "?"
    pend[o] += 1
for k, v in pend.most_common(8):
    print(f"   {v:5d}  {k}")
print()
print("== review store ==")
try:
    print("   recorded human decisions:", con.execute("SELECT COUNT(*) FROM review_decisions").fetchone()[0])
except sqlite3.OperationalError:
    print("   (no review_decisions table yet)")
print()
print("== map path: does any event now satisfy the venue requirement? ==")
ver = con.execute("""SELECT COUNT(DISTINCT event_id) c FROM crawler_evidence
                     WHERE field_name='venue_id' AND verification_status='Verified'""").fetchone()[0]
print(f"   events with a Verified venue_id: {ver} of {len(events)}")
coords = con.execute("SELECT COUNT(*) FROM venues WHERE payload LIKE '%coordinates%' AND payload NOT LIKE '%\"coordinates\": null%'").fetchone()[0]
print(f"   venues carrying coordinates   : {coords}")
con.close()
