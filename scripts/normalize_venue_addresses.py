"""Rewrite name-derived venue addresses as the address part of the source's own place string.

Why this exists: the venue row's ``address`` used to be the whole ``location`` claim, so a 豆瓣
place line was stored verbatim —

    苏州 吴中区 山丘livehouse-斜塘店 松涛街1088号斜塘老街36幢

— and that is what a human reads when entering coordinates and what the address resolver sends to
AMap. The claim was never wrong; it was simply not an address. New rows get the derived address at
crawl time (``crawler/addresses.py``); this script brings the rows that already exist in line.

Only rows whose stored address is *exactly* one of the ``location`` claims recorded for their own
events are touched, so a value somebody typed is never overwritten, and a row whose address came
from somewhere else (the alias file's canonical rows, the curated coordinates list) is left alone.
Evidence for every rewrite is printed and written to the JSON report.

Dry-run by default; pass --apply to write.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database import connect  # noqa: E402
from crawler.addresses import lookup_address, street_address  # noqa: E402

DEFAULT_DB = Path("backend/data/menduner.sqlite3")


def claims_for_venue(con, venue_id):
    """``[(claim, source, source_url)]`` — the location claims of this venue's own events.

    The claim is stored as the JSON value the extractor recorded, so it is decoded here; a claim
    that is not JSON is kept as-is.
    """
    rows = con.execute(
        "SELECT DISTINCT ce.value AS value, ce.source AS source, ce.source_url AS url "
        "FROM crawler_evidence ce JOIN events ev ON ev.id = ce.event_id "
        "WHERE ev.venue = ? AND ce.field_name = 'location' "
        "AND ce.value IS NOT NULL AND ce.value <> 'null'",
        (venue_id,),
    ).fetchall()
    out = []
    for row in rows:
        raw = row["value"]
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            value = raw
        if isinstance(value, str) and value.strip():
            out.append((value, row["source"], row["url"]))
    return out


def plan(con):
    """``[(venue_id, name, before, after, claim, source, url)]`` for every row to rewrite."""
    changes = []
    for row in con.execute("SELECT id, payload FROM venues ORDER BY id"):
        payload = json.loads(row["payload"])
        name = payload.get("name")
        before = payload.get("address")
        claims = claims_for_venue(con, row["id"])
        derived = None
        evidence = None
        for claim, source, url in claims:
            candidate = street_address(claim, venue_name=name)
            if candidate:
                derived, evidence = candidate, (claim, source, url)
                break
        if derived is None or derived == before:
            continue
        if before is not None and before not in [claim for claim, _, _ in claims]:
            # Not a value this pipeline derived: leave a curated/manual address alone.
            continue
        changes.append((row["id"], name, before, derived, *evidence))
    return changes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", type=Path, help="write the plan/result as JSON")
    args = parser.parse_args()
    if not args.db.exists():
        print(f"missing database: {args.db}")
        return 1

    with connect(args.db) as con:
        changes = plan(con)
        print(f"database: {args.db}")
        print(f"venue rows to rewrite: {len(changes)}\n")
        for venue_id, name, before, after, claim, source, url in changes:
            print(f"  {name}")
            print(f"    claim  : {claim}   [{source}]")
            print(f"    before : {before}")
            print(f"    after  : {after}")
            print(f"    lookup : {lookup_address(claim)}")
        if args.apply and changes:
            for venue_id, name, before, after, *_ in changes:
                row = con.execute("SELECT payload FROM venues WHERE id=?", (venue_id,)).fetchone()
                payload = json.loads(row["payload"])
                payload["address"] = after
                con.execute("UPDATE venues SET payload=? WHERE id=?",
                            (json.dumps(payload, ensure_ascii=False, sort_keys=True), venue_id))

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(
            [dict(venue_id=c[0], name=c[1], before=c[2], after=c[3], claim=c[4], source=c[5],
                  source_url=c[6], lookup=lookup_address(c[4])) for c in changes],
            ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nreport: {args.report}")

    if not args.apply:
        print("\nDRY RUN: pass --apply to write the derived addresses")
    else:
        print(f"\nAPPLIED: {len(changes)} venue addresses rewritten")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
