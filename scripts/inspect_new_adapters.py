"""Inspect the events stored by the visitsz and douban adapters."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

for name in sys.argv[1:]:
    db = Path(name)
    if not db.exists():
        print(f"MISSING {db}")
        continue
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    print(f"\n{'=' * 88}\n{db.name}")
    print("=" * 88)

    for r in con.execute(
            "SELECT event_id, normalized_json FROM crawler_unified_events ORDER BY event_id"):
        d = json.loads(r["normalized_json"])
        print(f"\n  {d.get('event_name')}")
        print(f"    start={d.get('start_date')}  end={d.get('end_date')}  "
              f"category={d.get('category')}")
        print(f"    venue={d.get('venue')}")
        print(f"    location={d.get('location')}")
        print(f"    organizer={d.get('organizer')}")
        print(f"    source_url={d.get('source_url')}")

    print("\n  -- evidence status roll-up --")
    for r in con.execute(
            "SELECT verification_status, COUNT(*) c FROM crawler_evidence "
            "GROUP BY verification_status ORDER BY c DESC"):
        print(f"    {r['verification_status']:14s} {r['c']}")
    verified = con.execute(
        "SELECT COUNT(*) FROM crawler_evidence WHERE verification_status='Verified'"
    ).fetchone()[0]
    print(f"    VERIFIED ROWS: {verified}  (must be 0)")

    print("\n  -- provenance: every evidence row keeps a source URL --")
    print("    rows without source_url:",
          con.execute("SELECT COUNT(*) FROM crawler_evidence "
                      "WHERE source_url IS NULL OR source_url=''").fetchone()[0])

    print("\n  -- raw pages retained --")
    for r in con.execute(
            "SELECT item_key, validation_status, original_url FROM crawler_raw_items "
            "ORDER BY validation_status, item_key LIMIT 30"):
        print(f"    [{r['validation_status']:9s}] {r['original_url'][:88]}")
    con.close()
