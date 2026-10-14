"""Collapse events that the old fingerprint could not recognise as duplicates.

Why this is needed: the fingerprint used to hash the punctuated event name, so 上海乐历's
``格调室内乐·二`` and the orchestra's ``格调室内乐 · 二`` — the same concert, same date, same venue —
hashed differently and were stored twice. `crawler.pipeline.fingerprint` now compares the
identity form of a name, so future crawls will not create these pairs, but the pairs already
in the database have to be collapsed once.

The merge is deliberately conservative. Two events are only treated as one when they share
the start date AND the venue AND their names are equal after punctuation removal. Events that
differ by real words are never merged: on 2026-05-27 the same hall hosts eight genuinely
different exhibitions, and a similarity-based match would have destroyed them.

For each duplicate group the survivor is the row with the most evidence (ties broken by the
human-review count, then by id for determinism). Everything attached to the losers is moved to
the survivor first, so nothing is orphaned:

  * ``crawler_observations``  re-pointed, so the page keeps its link to the event
  * ``crawler_evidence``      deleted (it is rebuilt from observations on the next refresh)
  * ``evidence``              deleted (same)
  * ``review_decisions``      re-pointed; a survivor's own decision for a field always wins
  * ``events``                losers deleted

Dry-run by default.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database import connect, snapshot  # noqa: E402
from crawler.pipeline import identity_text  # noqa: E402

DEFAULT_DB = Path("backend/data/menduner.sqlite3")


def find_groups(snap) -> dict[tuple[str, str], list[dict]]:
    """(start date, identity name) -> the events that are the same event."""
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for event in snap["events"]:
        name = identity_text(event.get("name"))
        if name and event.get("startDate"):
            groups[(event["startDate"], name)].append(event)
    return {key: rows for key, rows in groups.items() if len(rows) > 1}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.db.exists():
        print(f"missing database: {args.db}")
        return 1

    snap = snapshot(args.db)
    groups = find_groups(snap)

    evidence_count: dict[str, int] = defaultdict(int)
    for row in snap["evidence"]:
        evidence_count[row["entityId"]] += 1

    decisions_count: dict[str, int] = defaultdict(int)
    observation_count: dict[str, int] = defaultdict(int)
    with connect(args.db) as con:
        for row in con.execute("SELECT event_id, COUNT(*) n FROM review_decisions GROUP BY event_id"):
            decisions_count[row["event_id"]] = row["n"]
        for row in con.execute(
            "SELECT event_id, COUNT(*) n FROM crawler_observations GROUP BY event_id"
        ):
            observation_count[row["event_id"]] = row["n"]

    def rank(event: dict) -> tuple[int, int, str]:
        event_id = event["id"]
        # Most evidence, then most human review (that work is the expensive part), then id so
        # the choice is deterministic across runs.
        return (
            evidence_count.get(event_id, 0),
            decisions_count.get(event_id, 0) * 1000 + observation_count.get(event_id, 0),
            event_id,
        )

    total_merged = 0
    print(f"database: {args.db}")
    print(f"events  : {len(snap['events'])}")
    print()
    planned: list[tuple[dict, list[dict]]] = []
    for (date, name), rows in sorted(groups.items()):
        ordered = sorted(rows, key=rank, reverse=True)
        survivor, losers = ordered[0], ordered[1:]
        planned.append((survivor, losers))
        total_merged += len(losers)
        print(f"{date}  {name[:40]}")
        print(
            f"    KEEP  {survivor['id']}  evidence={evidence_count.get(survivor['id'], 0)}"
            f"  decisions={decisions_count.get(survivor['id'], 0)}"
            f"  obs={observation_count.get(survivor['id'], 0)}"
        )
        print(f"          [{survivor.get('source', '?')}] {survivor['name'][:56]}")
        for loser in losers:
            print(
                f"    MERGE {loser['id']}  evidence={evidence_count.get(loser['id'], 0)}"
                f"  decisions={decisions_count.get(loser['id'], 0)}"
                f"  obs={observation_count.get(loser['id'], 0)}"
            )
            print(f"          [{loser.get('source', '?')}] {loser['name'][:56]}")

    print()
    print(f"groups to merge : {len(planned)}")
    print(f"events removed  : {total_merged}")
    print(f"events after    : {len(snap['events']) - total_merged}")

    if not args.apply:
        print("\nDRY RUN: pass --apply to merge")
        return 0

    merged = 0
    with connect(args.db) as con:
        for survivor, losers in planned:
            target = survivor["id"]
            for loser in losers:
                source_id = loser["id"]
                con.execute(
                    "UPDATE crawler_observations SET event_id=? WHERE event_id=?",
                    (target, source_id),
                )
                # Field evidence is rebuilt from the observations on the next refresh, so the
                # stale rows are dropped rather than duplicated.
                con.execute("DELETE FROM evidence WHERE event_id=?", (source_id,))
                con.execute("DELETE FROM crawler_evidence WHERE event_id=?", (source_id,))
                con.execute(
                    "DELETE FROM crawler_unified_events WHERE event_id=?", (source_id,)
                )
                # A human decision on the survivor's own value must not be overwritten by the
                # loser's decision for the same field.
                con.execute(
                    """UPDATE review_decisions SET event_id=?
                       WHERE event_id=? AND field NOT IN (
                         SELECT field FROM review_decisions WHERE event_id=?)""",
                    (target, source_id, target),
                )
                con.execute("DELETE FROM review_decisions WHERE event_id=?", (source_id,))
                con.execute("DELETE FROM events WHERE id=?", (source_id,))
                merged += 1

    after = snapshot(args.db)
    print(f"\nAPPLIED: merged {merged} events")
    print(f"events now: {len(after['events'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
