"""One-off migration: point existing event rows at canonical venues.

New crawls resolve duplicate venue identities through ``crawler/venue_aliases.json``, but
rows written before that mapping existed still reference the duplicate venue id. This
rewrites those references and removes the superseded venue rows, which is what lets a
venue's verified geography reach the events that happen there.

Dry-run by default; pass --apply to write. Report every row it touches.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from crawler.venues import ALIAS_PATH, alias_ids, canonical_venue_id  # noqa: E402

DEFAULT_DB = Path("backend/data/menduner.sqlite3")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--apply", action="store_true", help="write the changes")
    parser.add_argument("--aliases", type=Path, default=ALIAS_PATH)
    args = parser.parse_args()

    aliases = alias_ids(args.aliases)
    if not aliases:
        print("no aliases configured; nothing to do")
        return 0
    if not args.db.exists():
        print(f"missing database: {args.db}")
        return 1

    con = sqlite3.connect(str(args.db))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")

    print(f"database: {args.db}")
    print(f"aliases : {sorted(aliases)}")

    moved = 0
    print("\n== events to repoint ==")
    for alias in sorted(aliases):
        canonical = canonical_venue_id(alias, args.aliases)
        rows = con.execute(
            "SELECT id, name FROM events WHERE venue=?", (alias,)
        ).fetchall()
        for row in rows:
            print(f"  {row['id']}  {str(row['name'])[:44]:44s}  {alias} -> {canonical}")
            if args.apply:
                con.execute(
                    "UPDATE events SET venue=? WHERE id=?", (canonical, row["id"])
                )
                payload = json.loads(
                    con.execute(
                        "SELECT payload FROM events WHERE id=?", (row["id"],)
                    ).fetchone()["payload"]
                )
                payload["venueId"] = canonical
                con.execute(
                    "UPDATE events SET payload=? WHERE id=?",
                    (json.dumps(payload, ensure_ascii=False, sort_keys=True), row["id"]),
                )
                con.execute(
                    "UPDATE crawler_unified_events SET normalized_json=? WHERE event_id=?",
                    (
                        json.dumps(payload, ensure_ascii=False, sort_keys=True),
                        row["id"],
                    ),
                )
        moved += len(rows)

    print("\n== observations to repoint ==")
    obs_moved = 0
    for alias in sorted(aliases):
        canonical = canonical_venue_id(alias, args.aliases)
        rows = con.execute(
            "SELECT source_id, item_key, normalized_json FROM crawler_observations"
        ).fetchall()
        for row in rows:
            try:
                document = json.loads(row["normalized_json"])
            except ValueError:
                continue
            if document.get("venue_id") != alias:
                continue
            print(f"  {row['source_id']}/{row['item_key']}  {alias} -> {canonical}")
            if args.apply:
                document["venue_id"] = canonical
                con.execute(
                    "UPDATE crawler_observations SET normalized_json=? "
                    "WHERE source_id=? AND item_key=?",
                    (
                        json.dumps(document, ensure_ascii=False, sort_keys=True),
                        row["source_id"],
                        row["item_key"],
                    ),
                )
            obs_moved += 1

    print("\n== events.venue column references ==")
    tail = 0
    for row in con.execute("SELECT id, venue FROM events WHERE venue IS NOT NULL"):
        if row["venue"] in aliases:
            print(f"  still alias: {row['id']} -> {row['venue']}")
            tail += 1

    print("\n== superseded venue rows ==")
    for alias in sorted(aliases):
        row = con.execute("SELECT payload FROM venues WHERE id=?", (alias,)).fetchone()
        if row:
            print(f"  {alias}: {json.loads(row['payload']).get('name')}")
            if args.apply:
                con.execute("DELETE FROM venues WHERE id=?", (alias,))

    if args.apply:
        con.commit()
        print(f"\nAPPLIED: {moved} events, {obs_moved} observations repointed")
    else:
        print(
            f"\nDRY RUN: would repoint {moved} events and {obs_moved} observations "
            f"(pass --apply to write)"
        )
    con.close()
    return 0 if tail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
