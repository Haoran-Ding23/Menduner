"""Check evidence entity references against live resource tables."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

DB = Path(sys.argv[1] if len(sys.argv) > 1 else "backend/data/menduner.sqlite3")
con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
con.row_factory = sqlite3.Row

print("== resource tables ==")
for t in ("venues", "hotels", "districts"):
    ids = [r[0] for r in con.execute(f"SELECT id FROM {t} ORDER BY id")]
    print(f"  {t:10s} ({len(ids)}): {ids}")

print("\n== event venue/district references ==")
for r in con.execute("SELECT id, venue, district FROM events ORDER BY id"):
    print(f"  {r['id'][:30]:30s} venue={r['venue']} district={r['district']}")

print("\n== dangling event -> resource references ==")
for col, table in (("venue", "venues"), ("district", "districts")):
    rows = con.execute(
        f"""SELECT DISTINCT e.{col} AS ref FROM events e
            WHERE e.{col} IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM {table} t WHERE t.id = e.{col})"""
    ).fetchall()
    print(f"  events.{col} -> {table}: dangling = {[r['ref'] for r in rows]}")

print("\n== evidence entity references ==")
rows = con.execute(
    """SELECT DISTINCT entity_id FROM evidence
       WHERE event_id IS NULL ORDER BY entity_id"""
).fetchall()
for r in rows:
    eid = r["entity_id"]
    found = {}
    for t in ("venues", "hotels", "districts", "events"):
        found[t] = con.execute(
            f"SELECT COUNT(*) FROM {t} WHERE id=?", (eid,)
        ).fetchone()[0]
    dangling = not any(found.values())
    n = con.execute(
        "SELECT COUNT(*) FROM evidence WHERE entity_id=?", (eid,)
    ).fetchone()[0]
    print(f"  {eid:14s} rows={n}  venues={found['venues']} hotels={found['hotels']} "
          f"districts={found['districts']} events={found['events']}  "
          f"{'<-- DANGLING' if dangling else ''}")

print("\n== totals ==")
print("  evidence rows total          :", con.execute("SELECT COUNT(*) FROM evidence").fetchone()[0])
print("  event-linked evidence rows   :",
      con.execute("SELECT COUNT(*) FROM evidence WHERE event_id IS NOT NULL").fetchone()[0])
print("  POI evidence rows            :",
      con.execute("SELECT COUNT(*) FROM evidence WHERE event_id IS NULL").fetchone()[0])
con.close()
