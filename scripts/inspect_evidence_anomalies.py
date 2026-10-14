"""Investigate evidence-row anomalies in the production database."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

DB = Path(sys.argv[1] if len(sys.argv) > 1 else "backend/data/menduner.sqlite3")
con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
con.row_factory = sqlite3.Row


def show(title, rows):
    print(f"\n== {title} ==")
    for r in rows:
        print("  ", dict(r))


show("Verified evidence (should normally be zero from crawling)", con.execute(
    "SELECT id, event_id, entity_id, field, value, source_url, verification_status "
    "FROM evidence WHERE verification_status='Verified' LIMIT 15"))

show("Evidence with no source_url", con.execute(
    "SELECT id, event_id, entity_id, field, value, source_url, verification_status "
    "FROM evidence WHERE source_url IS NULL OR source_url='' LIMIT 15"))

show("Evidence not linked to an event", con.execute(
    "SELECT id, event_id, entity_id, field, value, source_url, verification_status "
    "FROM evidence WHERE event_id IS NULL LIMIT 15"))

print("\n== evidence entity kinds ==")
for r in con.execute("SELECT entity_id, COUNT(*) c FROM evidence GROUP BY entity_id ORDER BY c DESC LIMIT 20"):
    print(f"   {r['entity_id']:44s} {r['c']}")

print("\n== evidence table columns ==")
print("  ", [d[1] for d in con.execute("PRAGMA table_info(evidence)")])
print("  crawler_evidence columns:")
print("  ", [d[1] for d in con.execute("PRAGMA table_info(crawler_evidence)")])

print("\n== crawler_evidence rows ==")
print("  count:", con.execute("SELECT COUNT(*) FROM crawler_evidence").fetchone()[0])
for r in con.execute(
        "SELECT event_id, field_name, value, source_url, verification_status, confidence "
        "FROM crawler_evidence ORDER BY event_id, field_name LIMIT 20"):
    print(f"   {r['event_id'][:26]:26s} {r['field_name']:12s} {str(r['value'])[:30]:30s} "
          f"{r['verification_status']:12s} {str(r['source_url'])[:60]}")

print("\n== status payload served by the API ==")
print("  sources:", con.execute("SELECT COUNT(*) FROM sources").fetchone()[0])
print("  events :", con.execute("SELECT COUNT(*) FROM events").fetchone()[0])
con.close()
