"""Small-source pipeline with durable raw provenance and per-source publication."""

import hashlib
import html
import json
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from backend.database import aggregate_status, connect, initialize
from backend.models import EventRecord, EvidenceRecord
from crawler.extractor import extract, text
from crawler.validator import validate
from crawler.storage import put_evidence
from crawler.venues import canonical_venue_id, canonical_venue_rows
from crawler.addresses import venue_address
from crawler import crawl_log, review, verification

REFERENCE_FILE = (
    Path(__file__).resolve().parents[1] / "demo" / "fixtures" / "references.json"
)
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


def identity_text(value):
    """Comparison-only form of an event name or venue name.

    Two sources publish the same event with different punctuation — 上海乐历 writes
    ``格调室内乐·二`` where the orchestra writes ``格调室内乐 · 二``, and ``巨人的肖像:…`` against
    ``巨人的肖像——…``. The old fingerprint compared punctuated strings, so the same concert
    was stored twice and counted twice in every total.

    Whitespace and punctuation are therefore removed and only the information-bearing
    characters are kept. Deliberately NOT a similarity measure: ``绝缘与导电材料展`` and
    ``导热/散热材料展`` remain different events, which a ratio-based match would have merged.
    """
    if value is None:
        return None
    normalized = unicodedata.normalize("NFKC", html.unescape(str(value))).casefold()
    return "".join(
        character
        for character in normalized
        if not character.isspace()
        and not unicodedata.category(character).startswith(("P", "Z", "C", "S"))
    )


def fingerprint(event):
    # Never fuzzy-merge different dates or records without dates/location context.
    place = event.get("venue_id") or event.get("venue") or event.get("location")
    if not event.get("start_date") or not place:
        return None
    name = identity_text(event["event_name"])
    where = identity_text(place)
    # A key built only from punctuation would merge unrelated events.
    if not name or not where:
        return None
    return hashlib.sha256(dump([name, event["start_date"], where]).encode()).hexdigest()


def legacy_shape(row):
    payload = json.loads(row["payload"])
    return dict(
        event_name=payload["name"],
        start_date=payload["startDate"],
        venue_id=payload.get("venueId"),
        venue=payload.get("venueName"),
        location=payload.get("location"),
    )


def identify(con, source, item_key, event, mock):
    link = con.execute(
        "SELECT event_id FROM crawler_observations WHERE source_id=? AND item_key=?",
        (source, item_key),
    ).fetchone()
    if link:
        linked = con.execute(
            "SELECT payload FROM events WHERE id=?", (link["event_id"],)
        ).fetchone()
        if bool(json.loads(linked["payload"]).get("demo")) != mock:
            raise ValueError("Cannot merge real and demo event provenance")
        return link["event_id"], False, False
    key = fingerprint(event)
    candidates = set()
    if key:
        for row in con.execute(
            "SELECT u.event_id,e.payload FROM crawler_unified_events u JOIN events e ON e.id=u.event_id WHERE u.fingerprint=?",
            (key,),
        ):
            if bool(json.loads(row["payload"]).get("demo")) == mock:
                candidates.add(row["event_id"])
        for row in con.execute(
            "SELECT * FROM events WHERE id NOT IN (SELECT event_id FROM crawler_unified_events)"
        ):
            if (
                bool(json.loads(row["payload"]).get("demo")) == mock
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
        if bool(json.loads(existing["payload"]).get("demo")) != mock:
            raise ValueError("Cannot merge real and demo event provenance")
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


def withdraw_new_events(path, known_before):
    """Undo events created by a publish() attempt that failed part-way through.

    The source batch is meant to be atomic. A failure inside ``publish`` can leave the
    events and observations written before the failure committed, which produces rows that
    carry the failed source's id while their raw items say ``Failed``. Removing an event
    that did not exist before the attempt also removes its observations, unified record
    and evidence, because those are what made it exist.

    An event that already existed is deliberately kept: it has other sources' evidence and
    withdrawing it would delete valid history.
    """
    with connect(path) as con:
        created = [
            r["id"]
            for r in con.execute("SELECT id FROM events")
            if r["id"] not in known_before
        ]
        for event_id in created:
            con.execute("DELETE FROM evidence WHERE event_id=?", (event_id,))
            con.execute("DELETE FROM crawler_evidence WHERE event_id=?", (event_id,))
            con.execute("DELETE FROM crawler_observations WHERE event_id=?", (event_id,))
            con.execute("DELETE FROM crawler_unified_events WHERE event_id=?", (event_id,))
            con.execute("DELETE FROM events WHERE id=?", (event_id,))
    return len(created)


def source_metadata(adapters):
    """Per-source facts the auto-verification rule needs, taken from the registry.

    ``trust_level`` comes from ``crawler/source_registry.yaml`` (the authoritative-source
    gate) and ``extractor`` from the adapter's configured extractor key. Both are passed
    explicitly rather than inferred, so the rule cannot silently treat an unregistered
    source as authoritative.
    """
    return {
        adapter.source_id: dict(
            trust_level=getattr(adapter, "trust_level", None),
            extractor=getattr(adapter, "extractor", None),
        )
        for adapter in adapters
    }


def claim_method(observation, field, meta):
    """The extraction method recorded for one field claim, with a conservative default."""
    claim = observation.get("field_evidence", {}).get(field, {})
    method = claim.get("method")
    if method:
        return method
    # No method recorded: only treat it as deterministic when the adapter itself declares
    # a deterministic extractor. Anything else stays a heuristic.
    return meta.get("extractor") if meta else None


def refresh_event(con, event_id, now, source_meta=None):
    """Rebuild one event's canonical payload and field evidence from its observations.

    Does nothing when the event has no crawler observations. Legacy/demo rows are ingested
    through a different path and carry their evidence directly, so there is nothing to
    project; rebuilding them from an empty observation set would destroy their rows.
    """
    review.ensure_schema(con)
    source_meta = source_meta or {}
    observations = con.execute(
        "SELECT * FROM crawler_observations WHERE event_id=? ORDER BY source_id,item_key",
        (event_id,),
    ).fetchall()
    if not observations:
        return
    old = json.loads(
        con.execute("SELECT payload FROM events WHERE id=?", (event_id,)).fetchone()[
            "payload"
        ]
    )
    values = [(row, json.loads(row["normalized_json"])) for row in observations]
    decisions = review.decisions_for(con, event_id)
    canonical = {"event_id": event_id}
    states = {}
    fields = dict(FIELDS)
    if any(value.get("city") is not None or "city" in value.get("field_evidence", {}) for _, value in values):
        fields["city"] = "city"
    # Per-row decisions drive both the stored evidence and the event-level aggregate.
    # Conflict is an event-level fact, so it is computed before the per-row loop: several
    # observations disagreeing on a field means no single source is right.
    conflicted_fields = set()
    for field in fields:
        distinct = {
            dump(value[field]) for _, value in values if value.get(field) is not None
        }
        if field != "source_url" and len(distinct) > 1:
            conflicted_fields.add(field)
    row_states: dict[int, dict[str, str]] = {}
    row_decisions: dict[int, dict[str, dict | None]] = {}
    for index, (row, observation) in enumerate(values):
        meta = source_meta.get(row["source_id"], {})
        states_for_row: dict[str, str] = {}
        decided_for_row: dict[str, dict | None] = {}
        for field in fields:
            value = observation.get(field)
            claim = observation.get("field_evidence", {}).get(field, {})
            decision = verification.decide(
                field=field,
                value=value,
                method=claim_method(observation, field, meta),
                trust_level=meta.get("trust_level"),
                mock=bool(observation.get("mock", False)),
                existing_status="Conflicting" if field in conflicted_fields else None,
                # A field that is not auto-verifiable keeps the status its own extractor
                # declared, so normalising the claim never silently upgrades or erases it.
                status_fallback=claim.get("status", "Unverified"),
            )
            # Human decisions are keyed by the field name the API and UI use (the frontend
            # name). Looking them up under the backend name would make every recorded
            # decision silently inapplicable.
            status, human = review.overlay(decisions, fields[field], value, decision.status)
            states_for_row[field] = status
            # Keep the decision's origin for EVERY outcome, not only for verified claims.
            # Otherwise the UI cannot say whether a value is pending because the publisher
            # is an aggregator, because the extraction was a heuristic, or because the field
            # is not an auto-verifiable fact in the first place.
            decided_for_row[field] = human if human else {
                "decision": "Auto",
                "verified": decision.verified,
                "origin": decision.origin,
                "reason": decision.reason,
            }
        row_states[index] = states_for_row
        row_decisions[index] = decided_for_row
    # Second pass: a venue reference is a derived id, so the field rule leaves it pending.
    # It becomes verifiable only once the venue NAME it points at is verified, which is known
    # only after the first pass. Without this a venue's verified geography could never reach
    # the events held there, and the map would stay empty for legitimately verified data.
    for index, (row, observation) in enumerate(values):
        if "venue_id" not in fields:
            continue
        meta = source_meta.get(row["source_id"], {})
        verdict = verification.verify_venue_binding(
            reference_method=claim_method(observation, "venue_id", meta),
            venue_status=row_states[index].get("venue"),
            trust_level=meta.get("trust_level"),
            current_status=row_states[index].get("venue_id", ""),
        )
        if verdict is None:
            continue
        status, human = review.overlay(
            decisions, fields["venue_id"], observation.get("venue_id"), verdict.status
        )
        if human or status != "Verified":
            continue
        row_states[index]["venue_id"] = status
        row_decisions[index]["venue_id"] = {
            "decision": "Auto",
            "verified": True,
            "origin": verdict.origin,
            "reason": verdict.reason,
        }
    for field, frontend_field in fields.items():
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
            claims = [
                value.get("field_evidence", {}).get(field, {})
                for _, value in values
                if value.get(field) is not None
            ]
            aggregated = (
                aggregate_status([c.get("status", "Unverified") for c in claims])
                if unique
                else (
                    "Needs Review"
                    if any(
                        value.get("field_evidence", {}).get(field, {}).get("candidates")
                        for _, value in values
                    )
                    else "Missing"
                )
            )
            # A field is Verified only when every contributing observation is verified, so
            # one unreviewed aggregator copy cannot be hidden behind an official one.
            contributing = [
                row_states[i][field] for i in range(len(values)) if values[i][1].get(field) is not None
            ]
            if contributing and all(s == "Verified" for s in contributing):
                states[field] = "Verified"
            elif contributing and any(s == "Verified" for s in contributing):
                states[field] = aggregate_status(contributing)
            else:
                states[field] = aggregated
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
        demo=bool(old.get("demo")),
        attentionNote="Source observations; conflicts and inferred fields require review. Not automatically verified.",
    )
    # Individually valid observations can still form an invalid mixed interval.
    # Reject publication using the existing source transaction, preserving old state.
    if "city" in fields:
        payload["city"] = canonical["city"]
    EventRecord.model_validate(payload)
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
    # Refresh only evidence owned by this pipeline. Preserve external/manual records.
    con.execute(
        "DELETE FROM evidence WHERE id IN (SELECT id FROM crawler_evidence WHERE event_id=?)",
        (event_id,),
    )
    con.execute("DELETE FROM crawler_evidence WHERE event_id=?", (event_id,))
    for index, (row, observation) in enumerate(values):
        source = con.execute(
            "SELECT * FROM sources WHERE id=?", (row["source_id"],)
        ).fetchone()
        for field, frontend_field in fields.items():
            value = observation.get(field)
            field_claim = observation.get("field_evidence", {}).get(field, {})
            decision = row_decisions[index].get(field)
            # Per-row status: this observation's own source/method decision, already
            # overlaid with any matching human review decision for this value.
            status = row_states[index][field]
            confidence = (
                0.0
                if value is None
                else field_claim.get("confidence", 0.8 if source["mock"] else 0.0)
            )
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
            # ``decidedBy`` answers "who decided this value's status". An automatic decision
            # only counts when it actually VERIFIED the value: a claim left pending was not
            # decided by anyone, so it carries no decider even though the rule explains why.
            if decision is None:
                decided_by, decided_origin, decided_reason, decided_at = (
                    None, None, None, None,
                )
            elif decision.get("decision") == "Auto" and not decision.get("verified"):
                decided_by = None
                decided_origin = decision.get("origin")
                decided_reason = decision.get("reason")
                decided_at = None
            elif decision.get("decision") == "Auto":
                decided_by, decided_origin, decided_reason, decided_at = (
                    "automatic",
                    decision.get("origin"),
                    decision.get("reason"),
                    row["updated_at"],
                )
            else:
                corrects = decision.get("decision") == review.CORRECT
                decided_by = decision.get("reviewer") or "human"
                decided_origin = review.ORIGIN_HUMAN
                decided_reason = decision.get("note") or (
                    "human correction" if corrects else "human review decision"
                )
                decided_at = decision.get("decided_at")
            put_evidence(
                con,
                dict(
                    id=evidence_id,
                    entityId=event_id,
                    field=frontend_field,
                    field_name=field,
                    value=value,
                    status=status,
                    origin=(
                        # Why this field has its current status. A verified claim is
                        # prefixed with the verification channel; a pending one records only
                        # the reason so the UI can say whether it awaits review because the
                        # publisher is an aggregator, because the extraction was a heuristic,
                        # or because the field is not an auto-verifiable fact at all.
                        "verification:" + str(decided_origin)
                        if status == "Verified" and decided_origin
                        else str(decided_origin)
                        if decided_origin
                        else "pending:human_review"
                    ),
                    sourceUrl=observation["source_url"],
                    sourceName=source["name"],
                    source=row["source_id"],
                    method=field_claim.get(
                        "method",
                        (
                            "mock_structured_extraction"
                            if source["mock"]
                            else "deterministic_extraction"
                        ),
                    ),
                    snippet=field_claim.get("snippet"),
                    candidates=field_claim.get("candidates", []),
                    updatedAt=row["updated_at"],
                    raw_item_id=row["raw_item_id"],
                    sourceRole={"government": "government", "venue": "venue"}.get(
                        source["kind"], "other"
                    ),
                    confidence=confidence,
                    confidenceMethod="Extraction heuristic, not calibrated, not a fact probability; verification is separate",
                    decidedBy=decided_by,
                    decidedReason=decided_reason,
                    decidedAt=decided_at,
                    note=(
                        "Synthetic DEMO"
                        if source["mock"]
                        else (
                            "Automatically verified: "
                            + str(decided_reason or "")
                            if status == "Verified" and decided_by == "automatic"
                            else "Human-reviewed on the Evidence page"
                            if decided_by
                            else "Public source extraction; awaiting verification. Field snippets link to stored raw content."
                        )
                    ),
                ),
                event_id,
            )


def publish(con, adapter, accepted, now, references, allow_demo, source_meta=None):
    for resource in ("venues", "hotels", "districts"):
        for row in references[resource]:
            # Existing reference records take precedence; do not overwrite user enrichment.
            con.execute(
                f"INSERT OR IGNORE INTO {resource}(id,payload) VALUES(?,?)",
                (row["id"], dump(row)),
            )
    reference_ids = {row["id"] for group in references.values() for row in group}
    if allow_demo:
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
        event = dict(event)
        if not item.mock and event.get("venue"):
            key = text(event["venue"]).replace("·", "").replace(" ", "")
            venue_id = "venue-" + hashlib.sha256(key.encode()).hexdigest()[:20]
            # The venue row carries the ADDRESS part of the source's own place string; the claim
            # itself stays verbatim on the event's `location` field and its evidence. Without
            # this, a 豆瓣 place line like
            # "苏州 吴中区 山丘livehouse-斜塘店 松涛街1088号斜塘老街36幢" was stored as the address.
            address = venue_address(event.get("location"), event.get("venue"))
            canonical_id = canonical_venue_id(venue_id)
            if canonical_id != venue_id:
                # This name belongs to a venue that is already recorded under a canonical id.
                # Inserting the name-derived row first would recreate the very duplicate the
                # alias exists to collapse: an empty venue row that nothing references.
                canonical = next(
                    (
                        row
                        for row in canonical_venue_rows()
                        if row.get("id") == canonical_id
                    ),
                    None,
                )
                if canonical is None:
                    raise ValueError(
                        "Venue alias points at a canonical venue that is not declared: "
                        + str(canonical_id)
                    )
                references["venues"] = [
                    *[r for r in references["venues"] if r.get("id") != canonical["id"]],
                    canonical,
                ]
                con.execute(
                    "INSERT OR IGNORE INTO venues(id,payload) VALUES(?,?)",
                    (canonical["id"], dump(canonical)),
                )
                # If the superseded row exists from an earlier run, drop it when unused.
                con.execute(
                    """DELETE FROM venues WHERE id=?
                       AND NOT EXISTS (SELECT 1 FROM events WHERE venue=?)""",
                    (venue_id, venue_id),
                )
            else:
                con.execute(
                    "INSERT OR IGNORE INTO venues(id,payload) VALUES(?,?)",
                    (
                        venue_id,
                        dump(
                            dict(
                                id=venue_id,
                                name=event["venue"],
                                address=address,
                                districtId=None,
                                districtDemo=False,
                                coordinates=None,
                            )
                        ),
                    ),
                )
            event["venue_id"] = canonical_id
            event.setdefault("field_evidence", {})["venue_id"] = dict(
                confidence=0.6,
                status="Needs Review",
                method=(
                    "derived_reference_id_from_explicit_venue_name"
                    if event["venue_id"] == venue_id
                    else "canonical_duplicate_venue_identity"
                ),
                snippet=event["venue"],
            )
        event_id, duplicate, created = identify(
            con, adapter.source_id, item.item_key, event, item.mock
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
                demo=item.mock,
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
        refresh_event(con, event_id, now, source_meta)
        con.execute(
            "UPDATE crawler_raw_items SET validation_status='Published' WHERE id=?",
            (raw_id,),
        )
    return counts


def run_pipeline(path, adapters, *, allow_demo=False, request_client=None):
    adapters = list(adapters)
    request_start = len(request_client.requests) if request_client else 0
    page_start = len(request_client.pages) if request_client else 0
    if len({a.source_id for a in adapters}) != len(adapters):
        raise ValueError("Adapters must have unique source IDs")
    source_meta = source_metadata(adapters)
    initialize(path)
    from crawler.pipeline.cleanup import archive_demo

    archive = None if allow_demo else archive_demo(path)
    references = (
        json.loads(REFERENCE_FILE.read_text(encoding="utf-8"))
        if allow_demo
        else {"venues": [], "hotels": [], "districts": []}
    )
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
        mode="DEMO" if allow_demo else "REAL",
        demoArchive=archive,
        pagesCollected=0,
        rawRecordsCollected=0,
        evidenceRecordsGenerated=0,
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
    # Events per source before this run, so crawl_log can attribute growth to a source.
    counts_before: dict[str, int] = {}
    with connect(path) as baseline:
        for baseline_row in baseline.execute(
            "SELECT source_id, COUNT(DISTINCT event_id) n FROM crawler_observations "
            "GROUP BY source_id"
        ):
            counts_before[baseline_row["source_id"]] = baseline_row["n"]

    for adapter in adapters:
        attempt = dict(
            source=adapter.source_id,
            status="Success",
            accepted=0,
            rejected=0,
            error=None,
        )
        accepted = []
        repeated_raw_ids = []
        raw_ids = []
        items = []
        adapter_page_start = getattr(adapter, "pages_collected", 0)
        adapter_request_start = getattr(adapter, "request_attempts", 0)
        adapter_error_start = len(getattr(adapter, "errors", []))
        adapter_warning_start = len(getattr(adapter, "warnings", []))
        try:
            items = adapter.collect()
            if not allow_demo and (
                getattr(adapter, "mock", False) or any(item.mock for item in items)
            ):
                raise ValueError(
                    "Production pipeline refuses mock records; use crawler.demo.run with an isolated DB"
                )
            with connect(path) as con:
                con.execute(
                    "INSERT INTO sources VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,kind=excluded.kind,mock=excluded.mock,source_url=excluded.source_url,updated_at=excluded.updated_at",
                    (
                        adapter.source_id,
                        adapter.source_name,
                        adapter.kind,
                        int(getattr(adapter, "mock", False)),
                        adapter.source_url,
                        now,
                    ),
                )
                seen = {}
                collisions = set()
                for item in items:
                    # One shared JSON body may contain different event locators.
                    signature = (
                        item.raw_content, item.extractor, item.locator,
                        item.is_event, item.original_url, item.mock,
                    )
                    if (
                        item.item_key in seen
                        and seen[item.item_key] != signature
                    ):
                        collisions.add(item.item_key)
                    seen[item.item_key] = signature
                processed_keys = set()
                for item in items:
                    raw_id = uuid.uuid4().hex
                    raw_ids.append(raw_id)
                    error = None
                    repeated = item.item_key in processed_keys and item.item_key not in collisions
                    processed_keys.add(item.item_key)
                    try:
                        if item.item_key in collisions:
                            raise ValueError(
                                "Same source item key has incompatible raw records"
                            )
                        if repeated or not item.is_event:
                            event = None
                        else:
                            event = validate(
                                extract(item, adapter.kind), references
                            ).model_dump(mode="json")
                        if event is not None:
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
                            int(item.mock),
                            (
                                "Rejected"
                                if error
                                else "Duplicate" if repeated
                                else "Validated" if item.is_event else "Context"
                            ),
                            error,
                        ),
                    )
                    if repeated and item.is_event:
                        repeated_raw_ids.append(raw_id)
            # Raw history commits first. An event-write failure leaves forensic evidence intact.
            with connect(path) as con:
                known_before = {
                    r["id"] for r in con.execute("SELECT id FROM events")
                }
            try:
                with connect(path) as con:
                    con.execute("BEGIN IMMEDIATE")
                    counts = publish(con, adapter, accepted, now, references, allow_demo,
                                     source_meta)
            except Exception:
                # A failure part-way through publish() must not leave a half-published
                # source behind: without this, events written before the failure keep the
                # failed source's id while their raw items are marked Failed, and their
                # observations outlive the event rows they belonged to.
                withdraw_new_events(path, known_before)
                raise
            attempt["accepted"] = len(accepted)
            errors = getattr(adapter, "errors", [])[adapter_error_start:]
            warnings = getattr(adapter, "warnings", [])[adapter_warning_start:]
            attempt["requestErrors"] = errors
            attempt["warnings"] = warnings
            if errors:
                attempt["error"] = dump(errors)
            attempt["status"] = (
                "Partial" if attempt["rejected"] or errors or warnings else "Success"
            )
            if errors and not items:
                attempt["status"] = "Failed"
            if getattr(adapter, "require_events", False) and not accepted:
                attempt["status"] = "Failed"
                attempt["error"] = attempt["error"] or (
                    "No reliable event record passed extraction and validation; raw/context retained"
                )
            report["eventsProcessed"] += len(accepted)
            report["eventsCreated"] += counts["created"]
            report["eventsUpdated"] += counts["updated"]
            report["duplicatesDetected"] += counts["duplicates"] + len(repeated_raw_ids)
            report["sourcesProcessed"] += int(attempt["status"] != "Failed")
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
        attempt["pagesCollected"] = getattr(adapter, "pages_collected", 0) - adapter_page_start
        attempt["requestAttempts"] = getattr(adapter, "request_attempts", 0) - adapter_request_start
        attempt["contextRecords"] = sum(1 for item in items if not item.is_event)
        if getattr(adapter, "investigation", None):
            attempt["investigation"] = adapter.investigation
        report["pagesCollected"] += attempt["pagesCollected"]
        report["rawRecordsCollected"] += len(raw_ids)
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
    if request_client:
        report.update(request_client.audit_since(request_start, page_start))
    with connect(path) as con:
        report["rawRecordsCollected"] = con.execute(
            "SELECT COUNT(*) FROM crawler_raw_items WHERE job_id=?", (job_id,)
        ).fetchone()[0]
        report["evidenceRecordsGenerated"] = con.execute(
            "SELECT COUNT(*) FROM crawler_evidence"
        ).fetchone()[0]
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
        # Per-source history and consecutive-failure alerts. A failing source used to leave no
        # trace beyond the job report, so "this source broke three weeks ago" was unanswerable.
        report["crawlLog"] = crawl_log.record_run(
            con,
            report=report,
            started_at=request_start or finished,
            finished_at=finished,
            previous_counts=counts_before,
        )
    return report
