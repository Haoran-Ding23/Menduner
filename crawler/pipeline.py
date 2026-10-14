"""Small-source pipeline with durable raw provenance and per-source publication."""

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from backend.database import aggregate_status, connect, initialize
from backend.models import EvidenceRecord
from crawler.extractor import extract, text
from crawler.validator import validate
from crawler.legacy import put_evidence

REFERENCE_FILE = Path(__file__).with_name("fixtures") / "references.json"
FIELDS = {
    "event_name": "name",
    "category": "category",
    "start_date": "startDate",
    "end_date": "endDate",
    "venue": "venueName",
    "location": "location",
    "organizer": "organizer",
    "venue_id": "venueId",
    "district_id": "districtId",
    "source_url": "sourceUrl",
}


def stamp():
    return datetime.now(timezone.utc).isoformat()


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def fingerprint(event):
    # Never fuzzy-merge different dates or records without dates/location context.
    place = event.get("venue_id") or event.get("venue") or event.get("location")
    if not event.get("start_date") or not place:
        return None
    key = [
        text(event["event_name"]).casefold(),
        event["start_date"],
        text(place).casefold(),
    ]
    return hashlib.sha256(dump(key).encode()).hexdigest()


def legacy_shape(row):
    payload = json.loads(row["payload"])
    return dict(
        event_name=payload["name"],
        start_date=payload["startDate"],
        venue_id=payload.get("venueId"),
        venue=payload.get("venueName"),
        location=payload.get("location"),
    )


def identify(con, source, item_key, event):
    link = con.execute(
        "SELECT event_id FROM crawler_observations WHERE source_id=? AND item_key=?",
        (source, item_key),
    ).fetchone()
    if link:
        linked = con.execute(
            "SELECT payload FROM events WHERE id=?", (link["event_id"],)
        ).fetchone()
        if not json.loads(linked["payload"]).get("demo"):
            raise ValueError("Mock ingestion cannot update a non-DEMO event")
        return link["event_id"], False, False
    key = fingerprint(event)
    candidates = set()
    if key:
        for row in con.execute(
            "SELECT u.event_id,e.payload FROM crawler_unified_events u JOIN events e ON e.id=u.event_id WHERE u.fingerprint=?",
            (key,),
        ):
            if json.loads(row["payload"]).get("demo"):
                candidates.add(row["event_id"])
        for row in con.execute(
            "SELECT * FROM events WHERE id NOT IN (SELECT event_id FROM crawler_unified_events)"
        ):
            if (
                json.loads(row["payload"]).get("demo")
                and fingerprint(legacy_shape(row)) == key
            ):
                candidates.add(row["id"])
    if len(candidates) > 1:
        raise ValueError("Ambiguous duplicate identity; requires manual review")
    if candidates:
        return candidates.pop(), True, False
    existing = con.execute(
        "SELECT * FROM events WHERE id=?", (event["event_id"],)
    ).fetchone()
    if existing:
        if not json.loads(existing["payload"]).get("demo"):
            raise ValueError("Mock ingestion cannot update a non-DEMO event")
        # Stable IDs can update pre-V1.4 records only within the same source ownership.
        if (
            existing["source"] == source
            and not con.execute(
                "SELECT 1 FROM crawler_observations WHERE event_id=?", (existing["id"],)
            ).fetchone()
        ):
            return existing["id"], False, False
        raise ValueError(
            "Event ID collision with different identity; requires manual review"
        )
    return event["event_id"], False, True


def refresh_event(con, event_id, now):
    observations = con.execute(
        "SELECT * FROM crawler_observations WHERE event_id=? ORDER BY source_id,item_key",
        (event_id,),
    ).fetchall()
    old = json.loads(
        con.execute("SELECT payload FROM events WHERE id=?", (event_id,)).fetchone()[
            "payload"
        ]
    )
    values = [(row, json.loads(row["normalized_json"])) for row in observations]
    canonical = {"event_id": event_id}
    states = {}
    for field, frontend_field in FIELDS.items():
        candidates = [
            value[field] for _, value in values if value.get(field) is not None
        ]
        unique = list(dict.fromkeys(candidates))
        if field == "source_url":
            canonical[field] = values[0][1][field]
            states[field] = "Unverified"
        elif len(unique) > 1:
            previous = old.get(frontend_field)
            canonical[field] = previous if previous in unique else unique[0]
            states[field] = "Conflicting"
        else:
            canonical[field] = unique[0] if unique else None
            states[field] = "Unverified" if unique else "Missing"
    payload = dict(
        old,
        id=event_id,
        name=canonical["event_name"],
        category=canonical["category"],
        startDate=canonical["start_date"],
        endDate=canonical["end_date"],
        venueId=canonical["venue_id"],
        districtId=canonical["district_id"],
        venueName=canonical["venue"],
        location=canonical["location"],
        organizer=canonical["organizer"],
        sourceUrl=canonical["source_url"],
        demo=True,
        attentionNote="MOCK observations; conflicting fields require review, not automatic verification.",
    )
    primary = values[0][0]["source_id"]
    con.execute(
        "UPDATE events SET name=?,category=?,startDate=?,endDate=?,venue=?,district=?,source=?,verification_status=?,payload=? WHERE id=?",
        (
            payload["name"],
            payload["category"],
            payload["startDate"],
            payload["endDate"],
            payload["venueId"],
            payload["districtId"],
            primary,
            aggregate_status(list(states.values())),
            dump(payload),
            event_id,
        ),
    )
    con.execute(
        "INSERT INTO crawler_unified_events VALUES(?,?,?,?) ON CONFLICT(event_id) DO UPDATE SET fingerprint=excluded.fingerprint, normalized_json=excluded.normalized_json, updated_at=excluded.updated_at",
        (event_id, fingerprint(canonical), dump(canonical), now),
    )
    # Replace current evidence only. Immutable raw records retain history.
    con.execute("DELETE FROM evidence WHERE event_id=?", (event_id,))
    con.execute("DELETE FROM crawler_evidence WHERE event_id=?", (event_id,))
    for row, observation in values:
        source = con.execute(
            "SELECT * FROM sources WHERE id=?", (row["source_id"],)
        ).fetchone()
        for field, frontend_field in FIELDS.items():
            value = observation.get(field)
            status = "Missing" if value is None else states[field]
            confidence = 0.0 if value is None else 0.8
            evidence_id = (
                "v14:"
                + hashlib.sha256(
                    dump([event_id, row["source_id"], row["item_key"], field]).encode()
                ).hexdigest()
            )
            con.execute(
                "INSERT INTO crawler_evidence VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    evidence_id,
                    event_id,
                    field,
                    dump(value),
                    row["source_id"],
                    observation["source_url"],
                    confidence,
                    row["raw_item_id"],
                    status,
                ),
            )
            put_evidence(
                con,
                dict(
                    id=evidence_id,
                    entityId=event_id,
                    field=frontend_field,
                    field_name=field,
                    value=value,
                    status=status,
                    sourceUrl=observation["source_url"],
                    sourceName=source["name"],
                    source=row["source_id"],
                    method="mock_structured_extraction",
                    updatedAt=row["updated_at"],
                    raw_item_id=row["raw_item_id"],
                    sourceRole={"government": "government", "venue": "venue"}.get(
                        source["kind"], "other"
                    ),
                    confidence=confidence,
                    confidenceMethod="Synthetic structured-field score, not calibrated or a fact probability",
                    note="MOCK / Synthetic data. Reserved .invalid URL; no live website collected. Conflicting candidates remain unresolved.",
                ),
                event_id,
            )


def publish(con, adapter, accepted, now, references):
    for resource in ("venues", "hotels", "districts"):
        for row in references[resource]:
            # Existing reference records take precedence; do not overwrite user enrichment.
            con.execute(
                f"INSERT OR IGNORE INTO {resource}(id,payload) VALUES(?,?)",
                (row["id"], dump(row)),
            )
    reference_ids = {row["id"] for group in references.values() for row in group}
    prior_evidence = json.loads(
        (REFERENCE_FILE.parent / "evidence.json").read_text(encoding="utf-8")
    )
    for evidence in prior_evidence:
        if (
            evidence["entityId"] in reference_ids
            and not con.execute(
                "SELECT 1 FROM evidence WHERE entity_id=? AND field=?",
                (evidence["entityId"], evidence["field"]),
            ).fetchone()
        ):
            put_evidence(
                con, EvidenceRecord.model_validate(evidence).model_dump(), None
            )
    counts = {"created": 0, "updated": 0, "duplicates": 0}
    for raw_id, item, event in accepted:
        event_id, duplicate, created = identify(
            con, adapter.source_id, item.item_key, event
        )
        if created:
            payload = dict(
                id=event_id,
                name=event["event_name"],
                category=event["category"],
                startDate=event["start_date"],
                endDate=event["end_date"],
                venueId=event["venue_id"],
                districtId=event["district_id"],
                organizer=event["organizer"],
                attendance=None,
                sponsor=None,
                demo=True,
            )
            con.execute(
                "INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    event_id,
                    payload["name"],
                    payload["category"],
                    payload["startDate"],
                    payload["endDate"],
                    payload["venueId"],
                    payload["districtId"],
                    adapter.source_id,
                    "Unverified",
                    dump(payload),
                ),
            )
        counts["created" if created else "updated"] += 1
        counts["duplicates"] += int(duplicate)
        con.execute(
            "INSERT INTO crawler_observations VALUES(?,?,?,?,?,?) ON CONFLICT(source_id,item_key) DO UPDATE SET raw_item_id=excluded.raw_item_id, normalized_json=excluded.normalized_json, updated_at=excluded.updated_at",
            (adapter.source_id, item.item_key, event_id, raw_id, dump(event), now),
        )
        refresh_event(con, event_id, now)
        con.execute(
            "UPDATE crawler_raw_items SET validation_status='Published' WHERE id=?",
            (raw_id,),
        )
    return counts


def run_pipeline(path, adapters):
    adapters = list(adapters)
    if len({a.source_id for a in adapters}) != len(adapters):
        raise ValueError("Adapters must have unique source IDs")
    initialize(path)
    references = json.loads(REFERENCE_FILE.read_text(encoding="utf-8"))
    # Include previously configured resources when validating source relationships.
    with connect(path) as con:
        for resource in ("venues", "hotels", "districts"):
            merged = {r["id"]: r for r in references[resource]}
            merged.update(
                {
                    r["id"]: json.loads(r["payload"])
                    for r in con.execute(f"SELECT * FROM {resource}")
                }
            )
            references[resource] = list(merged.values())
    now = stamp()
    job_id = uuid.uuid4().hex
    report = dict(
        jobId=job_id,
        mode="MOCK",
        eventsProcessed=0,
        eventsCreated=0,
        eventsUpdated=0,
        duplicatesDetected=0,
        itemsRejected=0,
        sourcesProcessed=0,
        attempts=[],
    )
    with connect(path) as con:
        con.execute(
            "INSERT INTO crawler_jobs VALUES(?,?,NULL,?,NULL)", (job_id, now, "Running")
        )
    for adapter in adapters:
        attempt = dict(
            source=adapter.source_id,
            status="Success",
            accepted=0,
            rejected=0,
            error=None,
        )
        accepted = []
        raw_ids = []
        try:
            items = adapter.collect()
            with connect(path) as con:
                con.execute(
                    "INSERT INTO sources VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,kind=excluded.kind,mock=excluded.mock,source_url=excluded.source_url,updated_at=excluded.updated_at",
                    (
                        adapter.source_id,
                        adapter.source_name,
                        adapter.kind,
                        1,
                        adapter.source_url,
                        now,
                    ),
                )
                seen = {}
                collisions = set()
                for item in items:
                    if (
                        item.item_key in seen
                        and seen[item.item_key] != item.raw_content
                    ):
                        collisions.add(item.item_key)
                    seen[item.item_key] = item.raw_content
                for item in items:
                    raw_id = uuid.uuid4().hex
                    raw_ids.append(raw_id)
                    error = None
                    try:
                        if item.item_key in collisions:
                            raise ValueError(
                                "Same source item key has incompatible raw records"
                            )
                        event = validate(
                            extract(item, adapter.kind), references
                        ).model_dump(mode="json")
                        accepted.append((raw_id, item, event))
                    except (ValueError, KeyError, TypeError) as exc:
                        error = str(exc)
                        attempt["rejected"] += 1
                    con.execute(
                        "INSERT INTO crawler_raw_items VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            raw_id,
                            job_id,
                            adapter.source_id,
                            item.item_key,
                            item.original_url,
                            item.source_name,
                            item.crawl_time.isoformat(),
                            item.raw_content,
                            1,
                            "Rejected" if error else "Validated",
                            error,
                        ),
                    )
            # Raw history commits first. An event-write failure leaves forensic evidence intact.
            with connect(path) as con:
                con.execute("BEGIN IMMEDIATE")
                counts = publish(con, adapter, accepted, now, references)
            attempt["accepted"] = len(accepted)
            attempt["status"] = "Partial" if attempt["rejected"] else "Success"
            report["eventsProcessed"] += len(accepted)
            report["eventsCreated"] += counts["created"]
            report["eventsUpdated"] += counts["updated"]
            report["duplicatesDetected"] += counts["duplicates"]
            report["sourcesProcessed"] += 1
        except Exception as exc:
            attempt["status"] = "Failed"
            attempt["error"] = str(exc)
            attempt["rejected"] += len(accepted)
            with connect(path) as con:
                for raw_id, _, _ in accepted:
                    con.execute(
                        "UPDATE crawler_raw_items SET validation_status='Failed',error=? WHERE id=?",
                        (str(exc), raw_id),
                    )
        report["itemsRejected"] += attempt["rejected"]
        report["attempts"].append(attempt)
        with connect(path) as con:
            con.execute(
                "INSERT INTO crawler_attempts VALUES(?,?,?,?,?,?)",
                (
                    job_id,
                    adapter.source_id,
                    attempt["status"],
                    attempt["error"],
                    attempt["accepted"],
                    attempt["rejected"],
                ),
            )
    statuses = [a["status"] for a in report["attempts"]]
    report["status"] = (
        "Success"
        if statuses and all(s == "Success" for s in statuses)
        else "Partial" if report["sourcesProcessed"] else "Failed"
    )
    finished = stamp()
    report["updatedAt"] = finished
    with connect(path) as con:
        report["eventsStored"] = con.execute("SELECT COUNT(*) FROM events").fetchone()[
            0
        ]
        con.execute(
            "UPDATE crawler_jobs SET finished_at=?,status=?,report=? WHERE id=?",
            (finished, report["status"], dump(report), job_id),
        )
        if report["sourcesProcessed"]:
            con.execute(
                "INSERT INTO runs(updated_at,sources,event_count) VALUES(?,?,?)",
                (
                    finished,
                    dump(
                        [
                            a["source"]
                            for a in report["attempts"]
                            if a["status"] != "Failed"
                        ]
                    ),
                    report["eventsProcessed"],
                ),
            )
    return report
