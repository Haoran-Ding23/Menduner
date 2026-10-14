"""Archive synthetic event state before a real collection run. Never delete real events."""

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from backend.database import connect


def archive_demo(path):
    with connect(path) as con:
        ids = [
            r["id"]
            for r in con.execute("SELECT id,payload FROM events")
            if json.loads(r["payload"]).get("demo")
        ]
        mock_sources = [
            r["id"] for r in con.execute("SELECT id FROM sources WHERE mock=1")
        ]
        demo_districts = [
            r["id"]
            for r in con.execute("SELECT id,payload FROM districts")
            if json.loads(r["payload"]).get("demo")
        ]
        placeholders = {
            table: [
                r["id"]
                for r in con.execute(f"SELECT id,payload FROM {table}")
                if "DEMO" in json.loads(r["payload"]).get("name", "")
                and json.loads(r["payload"]).get("coordinates") is None
                and json.loads(r["payload"]).get("address") is None
                and json.loads(r["payload"]).get("districtDemo")
            ]
            for table in ("venues", "hotels")
        }
        if (
            not ids
            and not mock_sources
            and not demo_districts
            and not any(placeholders.values())
        ):
            return None
        backup = Path(
            str(path)
            + ".demo-archive-"
            + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            + "-"
            + uuid.uuid4().hex[:6]
            + ".sqlite3"
        )
        with sqlite3.connect(backup) as destination:
            con.backup(destination)
        con.execute("BEGIN IMMEDIATE")
        for event_id in ids:
            con.execute("DELETE FROM crawler_evidence WHERE event_id=?", (event_id,))
            con.execute(
                "DELETE FROM crawler_observations WHERE event_id=?", (event_id,)
            )
            con.execute(
                "DELETE FROM crawler_unified_events WHERE event_id=?", (event_id,)
            )
            con.execute("DELETE FROM events WHERE id=?", (event_id,))
        con.execute(
            "DELETE FROM crawler_raw_items WHERE mock=1 AND id NOT IN (SELECT raw_item_id FROM crawler_observations) AND id NOT IN (SELECT raw_item_id FROM crawler_evidence)"
        )
        for source in mock_sources:
            if (
                not con.execute(
                    "SELECT 1 FROM events WHERE source=?", (source,)
                ).fetchone()
                and not con.execute(
                    "SELECT 1 FROM crawler_raw_items WHERE source_id=?", (source,)
                ).fetchone()
            ):
                con.execute("DELETE FROM crawler_attempts WHERE source_id=?", (source,))
                con.execute("DELETE FROM sources WHERE id=?", (source,))
        for run in con.execute("SELECT * FROM runs").fetchall():
            sources = json.loads(run["sources"])
            if sources and all(s in mock_sources for s in sources):
                con.execute("DELETE FROM runs WHERE id=?", (run["id"],))
        # Audit history remains recoverable in the archive; active fake job reports are removed.
        for job in con.execute("SELECT id,report FROM crawler_jobs").fetchall():
            report = json.loads(job["report"]) if job["report"] else {}
            if (
                report.get("mode") in ("MOCK", "DEMO")
                and not con.execute(
                    "SELECT 1 FROM crawler_raw_items WHERE job_id=?", (job["id"],)
                ).fetchone()
            ):
                con.execute("DELETE FROM crawler_attempts WHERE job_id=?", (job["id"],))
                con.execute("DELETE FROM crawler_jobs WHERE id=?", (job["id"],))
        for table, resource_ids in placeholders.items():
            for resource_id in resource_ids:
                if (
                    table == "venues"
                    and con.execute(
                        "SELECT 1 FROM events WHERE venue=?", (resource_id,)
                    ).fetchone()
                ):
                    continue
                con.execute(
                    "DELETE FROM evidence WHERE event_id IS NULL AND entity_id=?",
                    (resource_id,),
                )
                con.execute(f"DELETE FROM {table} WHERE id=?", (resource_id,))
        for district_id in demo_districts:
            if con.execute(
                "SELECT 1 FROM events WHERE district=?", (district_id,)
            ).fetchone():
                continue
            for table in ("venues", "hotels"):
                for resource in con.execute(f"SELECT * FROM {table}").fetchall():
                    payload = json.loads(resource["payload"])
                    if payload.get("districtId") == district_id and payload.get(
                        "districtDemo"
                    ):
                        payload["districtId"] = None
                        payload["districtDemo"] = False
                        con.execute(
                            f"UPDATE {table} SET payload=? WHERE id=?",
                            (json.dumps(payload, ensure_ascii=False), resource["id"]),
                        )
                        for evidence in con.execute(
                            "SELECT * FROM evidence WHERE entity_id=? AND field='districtId'",
                            (resource["id"],),
                        ).fetchall():
                            value = json.loads(evidence["payload"])
                            value.update(
                                value=None,
                                status="Missing",
                                sourceUrl=None,
                                note="Archived legacy DEMO district grouping; no verified district association",
                            )
                            con.execute(
                                "UPDATE evidence SET value=?,source_url=NULL,verification_status=?,payload=? WHERE id=?",
                                (
                                    "null",
                                    "Missing",
                                    json.dumps(value, ensure_ascii=False),
                                    evidence["id"],
                                ),
                            )
            con.execute(
                "DELETE FROM evidence WHERE event_id IS NULL AND entity_id=?",
                (district_id,),
            )
            con.execute("DELETE FROM districts WHERE id=?", (district_id,))
        if con.execute("SELECT 1 FROM sources WHERE mock=1").fetchone():
            raise RuntimeError(
                "Legacy mock-source rows reference non-demo data; archived but cleanup rolled back. Review them manually before real crawling."
            )
    return str(backup)
