"""Verify the production database now contains only real, evidence-backed events."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

DB = Path(sys.argv[1] if len(sys.argv) > 1 else "backend/data/menduner.sqlite3")
con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
con.row_factory = sqlite3.Row

print(f"DB: {DB}  size={DB.stat().st_size}")


def q(sql, *p):
    return con.execute(sql, p).fetchall()


print("\n== contamination check ==")
print("  mock sources        :", q("SELECT COUNT(*) FROM sources WHERE mock=1")[0][0])
print("  mock raw items      :", q("SELECT COUNT(*) FROM crawler_raw_items WHERE mock=1")[0][0])
print("  demo events         :", q("SELECT COUNT(*) FROM events WHERE payload LIKE '%\"demo\": true%'")[0][0])
print("  events total        :", q("SELECT COUNT(*) FROM events")[0][0])
print("  evidence total      :", q("SELECT COUNT(*) FROM evidence")[0][0])

print("\n== sources ==")
for r in q("SELECT id, name, kind, mock, source_url FROM sources ORDER BY id"):
    print(f"  mock={r['mock']}  {r['id']:36s} {r['name'][:44]:44s} {r['kind']}")

print("\n== events (real) ==")
for r in q("""SELECT id, name, category, startDate, endDate, venue, district,
                     source, verification_status FROM events ORDER BY startDate"""):
    print(f"  {r['startDate'] or '          '} -> {r['endDate'] or '          '}  "
          f"[{r['category']:10s}] [{r['verification_status']:12s}] {r['name'][:46]}")
    print(f"        id={r['id']}  source={r['source']}  venue={r['venue']}")

print("\n== verification status ==")
for r in q("SELECT verification_status, COUNT(*) c FROM events GROUP BY verification_status"):
    print(f"  events        {r['verification_status']:14s} {r['c']}")
for r in q("SELECT verification_status, COUNT(*) c FROM evidence GROUP BY verification_status"):
    print(f"  evidence      {r['verification_status']:14s} {r['c']}")

print("\n== evidence fields ==")
for r in q("SELECT field, COUNT(*) c FROM evidence GROUP BY field ORDER BY c DESC"):
    print(f"  {r['field']:16s} {r['c']}")

print("\n== evidence provenance sample (start_date) ==")
for r in q("""SELECT event_id, field, value, source_url, verification_status
              FROM evidence WHERE field='start_date' LIMIT 6"""):
    print(f"  {r['event_id']:14s} {r['value']:>12s}  {r['verification_status']:12s} {r['source_url'][:78]}")

print("\n== every evidence row must keep a source URL ==")
print("  evidence without source_url:",
      q("SELECT COUNT(*) FROM evidence WHERE source_url IS NULL OR source_url=''")[0][0])
print("  evidence not linked to an event:",
      q("SELECT COUNT(*) FROM evidence WHERE event_id IS NULL")[0][0])
print("  evidence rows whose event is missing:",
      q("""SELECT COUNT(*) FROM evidence e
           WHERE e.event_id IS NOT NULL
             AND NOT EXISTS (SELECT 1 FROM events v WHERE v.id=e.event_id)""")[0][0])

print("\n== raw provenance ==")
for r in q("""SELECT item_key, original_url, source_name, crawl_time, mock, validation_status
              FROM crawler_raw_items ORDER BY crawl_time LIMIT 4"""):
    print(f"  mock={r['mock']} [{r['validation_status']}] {r['source_name'][:34]:34s} {r['original_url'][:74]}")

print("\n== job history ==")
for r in q("SELECT id, started_at, finished_at, status FROM crawler_jobs ORDER BY finished_at"):
    print(f"  {r['status']:8s} {r['started_at']} -> {r['finished_at']}  {r['id'][:12]}")

print("\n== integrity ==")
print("  integrity_check  :", q("PRAGMA integrity_check")[0][0])
print("  foreign_key_check:", q("PRAGMA foreign_key_check"))
print("  legacy mock-source refs:",
      q("SELECT COUNT(*) FROM events WHERE source IN (SELECT id FROM sources WHERE mock=1)")[0][0])
con.close()
