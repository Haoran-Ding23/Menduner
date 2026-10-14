"""Confirm venue references for a set of events in bulk.

A human reviewer who has established that a batch of events really is held at one venue
should not have to click through them one at a time. This writes an ordinary review decision
for each event's venue reference into the same durable store the Evidence page uses, so the
result is identical to clicking 通过 on each field: the decision is attributed, it survives
the next crawl, and it lapses if the reference changes.

Deliberately NOT run automatically by the crawler. It requires an explicit --venue, and it
prints every event it will touch before writing anything.

Usage:
  python scripts/confirm_venue_references.py --venue v-expo --reviewer "name" --dry-run
  python scripts/confirm_venue_references.py --venue v-expo --reviewer "name" --apply
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database import connect, snapshot  # noqa: E402
from crawler import review  # noqa: E402

DEFAULT_DB = Path("backend/data/menduner.sqlite3")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--venue", help="canonical venue id, e.g. v-expo")
    parser.add_argument(
        "--all-geocoded",
        action="store_true",
        help="every venue carrying verified coordinates, instead of a single venue",
    )
    parser.add_argument("--reviewer", required=True, help="who is confirming these")
    parser.add_argument(
        "--note",
        default="Venue identity confirmed for this batch of events",
        help="recorded with every decision",
    )
    parser.add_argument("--apply", action="store_true", help="write the decisions")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="explicitly request the default behaviour (report only, write nothing)",
    )
    args = parser.parse_args()

    if not args.venue and not args.all_geocoded:
        parser.error("select a venue with --venue or --all-geocoded")
    if not args.db.exists():
        print(f"missing database: {args.db}")
        return 1

    snap = snapshot(args.db)
    venues = {v["id"]: v for v in snap["venues"]}

    if args.all_geocoded:
        selected = {
            v["id"]
            for v in snap["venues"]
            if v.get("coordinates") and v["coordinates"].get("sourceUrl")
        }
        if args.venue:
            selected &= {args.venue}
    else:
        selected = {args.venue}
        if args.venue not in venues:
            print(f"unknown venue: {args.venue}")
            return 1

    evidence = {}
    for row in snap["evidence"]:
        evidence.setdefault(row["entityId"], {})[row["field"]] = row

    targets = []
    skipped = []
    for event in snap["events"]:
        if event.get("venueId") not in selected:
            continue
        claim = evidence.get(event["id"], {}).get("venueId")
        if claim is None or claim.get("status") == "Missing":
            skipped.append((event, "no venue reference claim"))
            continue
        if claim.get("status") == "Verified" and claim.get("decidedBy"):
            skipped.append((event, "already verified by a human"))
            continue
        targets.append((event, claim))

    target_venues = sorted({e["venueId"] for e, _ in targets})
    print(f"database : {args.db}")
    print(f"reviewer : {args.reviewer}")
    print(f"venues   : {len(target_venues)}")
    for vid in target_venues:
        v = venues[vid]
        print(f"   {vid:34s} {str(v.get('name'))[:34]:34s} coords={bool(v.get('coordinates'))}")
    print(f"\n== will confirm ({len(targets)}) ==")
    for event, claim in targets:
        print(f"  {event['startDate']}  {str(event['name'])[:52]:52s}  {claim['value']}")
    if skipped:
        print(f"\n== skipped ({len(skipped)}) ==")
        for event, why in skipped:
            print(f"  {str(event['name'])[:52]:52s}  {why}")

    if not args.apply:
        print("\nDRY RUN: pass --apply to record these decisions")
        return 0

    now = datetime.now(timezone.utc).isoformat()
    from backend.main import reproject_event

    for event, claim in targets:
        with connect(args.db) as con:
            review.record(
                con,
                event_id=event["id"],
                field="venueId",
                decision=review.APPROVE,
                reviewed_value=claim["value"],
                reviewer=args.reviewer,
                note=args.note,
                decided_at=now,
            )
        reproject_event(args.db, event["id"])

    after = snapshot(args.db)
    verified = {
        row["entityId"]
        for row in after["evidence"]
        if row["field"] == "venueId" and row["status"] == "Verified"
    }
    confirmed = sum(1 for event, _ in targets if event["id"] in verified)
    print(f"\nAPPLIED: {len(targets)} decisions recorded, {confirmed} references now Verified")
    remaining = [
        event for event, _ in targets if event["id"] not in verified
    ]
    if remaining:
        print("NOT verified (needs a look):")
        for event in remaining:
            print(f"  {str(event['name'])[:52]}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
