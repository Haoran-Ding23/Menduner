"""Read-only provenance inspection without adding frontend/API features."""

import argparse
import json
from pathlib import Path
from backend.database import connect, database_path


def main():
    parser = argparse.ArgumentParser(
        description="Inspect V1.4 jobs, normalized events or immutable raw records"
    )
    parser.add_argument("--db", type=Path, default=database_path())
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--event")
    group.add_argument("--job")
    group.add_argument("--raw-id")
    args = parser.parse_args()
    if not args.db.exists():
        parser.error("Database does not exist; run crawler first")
    try:
        with connect(args.db) as con:
            if args.event:
                unified = con.execute(
                    "SELECT * FROM crawler_unified_events WHERE event_id=?",
                    (args.event,),
                ).fetchone()
                if not unified:
                    parser.error("No V1.4 event record with that ID")
                data = dict(unified)
                data["normalized"] = json.loads(data.pop("normalized_json"))
                data["evidence"] = [
                    dict(r)
                    for r in con.execute(
                        "SELECT * FROM crawler_evidence WHERE event_id=? ORDER BY source,field_name",
                        (args.event,),
                    )
                ]
                for item in data["evidence"]:
                    item["value"] = json.loads(item["value"])
                data["raw_records"] = [
                    dict(r)
                    for r in con.execute(
                        "SELECT r.* FROM crawler_raw_items r JOIN crawler_observations o ON r.id=o.raw_item_id WHERE o.event_id=?",
                        (args.event,),
                    )
                ]
            elif args.raw_id:
                row = con.execute(
                    "SELECT * FROM crawler_raw_items WHERE id=?", (args.raw_id,)
                ).fetchone()
                if not row:
                    parser.error("Raw record not found")
                data = dict(row)
            else:
                row = (
                    con.execute(
                        "SELECT * FROM crawler_jobs WHERE id=?", (args.job,)
                    ).fetchone()
                    if args.job
                    else con.execute(
                        "SELECT * FROM crawler_jobs ORDER BY started_at DESC LIMIT 1"
                    ).fetchone()
                )
                if not row:
                    parser.error("No V1.4 job found")
                data = dict(row)
                data["report"] = json.loads(data["report"]) if data["report"] else None
                data["attempts"] = [
                    dict(r)
                    for r in con.execute(
                        "SELECT * FROM crawler_attempts WHERE job_id=?", (row["id"],)
                    )
                ]
        print(json.dumps(data, ensure_ascii=False, indent=2))
    except Exception as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
