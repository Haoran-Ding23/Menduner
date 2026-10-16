"""Move sampled places into a database, without touching anything else in it.

Why this exists: the sampling needs an AMap Web service key and runs wherever that key is, while
the authoritative venue coordinates live with the deployment. Rather than copy a 160 MB database
around — or paste a key onto a server — ``enrich_places.py`` writes the rows to a scratch database
and this script carries just those rows to the database that needs them.

It is additive and idempotent: rows are keyed by their AMap place id, so importing twice changes
nothing, and no other table is read or written.

Dry-run by default; pass --apply to write.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database import connect  # noqa: E402
from crawler import places as places_module  # noqa: E402


def load_rows(path: Path) -> list[dict]:
    document = json.loads(path.read_text(encoding="utf-8"))
    rows = document.get("places") if isinstance(document, dict) else document
    if not isinstance(rows, list):
        raise SystemExit("expected a list of place rows, or {\"places\": [...]}")
    out = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("id"):
            raise SystemExit("every row needs an id")
        if row.get("kind") not in places_module.KINDS:
            raise SystemExit(f"unexpected kind: {row.get('kind')!r}")
        out.append(row)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", type=Path, help="JSON file with the sampled rows")
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.source.exists() or not args.db.exists():
        raise SystemExit("missing source file or database")

    rows = load_rows(args.source)
    by_kind: dict[str, int] = {}
    for row in rows:
        by_kind[row["kind"]] = by_kind.get(row["kind"], 0) + 1
    print(f"source : {args.source}  rows={len(rows)}  {by_kind}")
    print(f"database: {args.db}")
    with connect(args.db) as con:
        places_module.ensure_schema(con)
        before = con.execute("SELECT COUNT(*) FROM places").fetchone()[0]
        existing = {row[0] for row in con.execute("SELECT id FROM places")}
        new_rows = [row for row in rows if row["id"] not in existing]
        print(f"places before: {before}  new: {len(new_rows)}  already present: {len(rows) - len(new_rows)}")
        if not args.apply:
            print("\nDRY RUN: pass --apply to write")
            return 0
        for row in rows:
            con.execute(
                "INSERT OR REPLACE INTO places(id,payload) VALUES(?,?)",
                (row["id"], json.dumps(row, ensure_ascii=False, sort_keys=True)),
            )
    with connect(args.db) as con:
        after = con.execute("SELECT COUNT(*) FROM places").fetchone()[0]
    print(f"\nAPPLIED: places now {after}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
