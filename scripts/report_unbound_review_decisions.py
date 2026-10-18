"""List review decisions that can no longer be trusted, and say why (read-only).

Before 2026-10-18 a decision could be recorded with ``reviewed_value`` NULL when the request
omitted the value, and ``resolve`` read NULL as "matches every value": one approval silently
kept verifying later values nobody had seen. Those rows now bind to the ABSENCE of the claim,
so the fields return to the review queue.

NULL is not always a defect: ``AbsentConfirmed`` is recorded with no value on purpose (the
reviewer confirmed the source states nothing). This script separates the two, so the re-review
is a known, finite task instead of a surprise.

Usage: report_unbound_review_decisions.py [db-path]
"""
import sqlite3
import sys

DB = sys.argv[1] if len(sys.argv) > 1 else "/srv/menduner/data/menduner.sqlite3"
VALID_WITHOUT_VALUE = ("AbsentConfirmed",)


def main():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    total = cur.execute("SELECT COUNT(*) FROM review_decisions").fetchone()[0]
    rows = cur.execute(
        "SELECT event_id, field, decision, reviewer, decided_at FROM review_decisions "
        "WHERE reviewed_value IS NULL ORDER BY decided_at"
    ).fetchall()
    broken = [r for r in rows if r["decision"] not in VALID_WITHOUT_VALUE]
    healthy = [r for r in rows if r["decision"] in VALID_WITHOUT_VALUE]
    print(f"decisions: {total}   without a bound value: {len(rows)}")
    print(f"  needs re-review (approved/rejected an unbounded claim): {len(broken)}")
    for row in broken:
        print(f"    {row['decided_at'][:19]}  {row['decision']:9} {row['field']:12} "
              f"{row['event_id']}  by {row['reviewer']}")
    print(f"  correct as-is (AbsentConfirmed records an absence): {len(healthy)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
