"""Venue maintenance reads and writes: duplicate resolution and coordinate entry.

Both operations are human decisions, so both are recorded with who made them and why:

  * ``review_decisions`` holds the event-level venue-reference approvals the Evidence page
    already uses, so confirming a merge also verifies the affected venue references;
  * ``venue_edits`` holds venue-row edits (a coordinate, a merge), which are not field
    claims and therefore do not belong in the evidence overlay.

Nothing here is called by the crawler.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from backend.database import connect, snapshot
from crawler import review
from crawler.venue_duplicates import (
    Candidate,
    default_alias_path,
    detect,
    load_aliases,
    write_alias,
)
from crawler.venues import canonical_venue_id, canonical_venue_rows, reset_cache

DDL = """
CREATE TABLE IF NOT EXISTS venue_edits (
  id TEXT PRIMARY KEY,
  venue_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  detail TEXT NOT NULL,
  reviewer TEXT NOT NULL,
  note TEXT,
  edited_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS venue_edits_venue_idx ON venue_edits(venue_id);
"""

# GCJ-02 (the coordinate system AMap publishes) bounds for the Suzhou area. A value outside
# these is a typo, not a venue, and would put a pin in the wrong hemisphere.
SUZHOU_BOUNDS = dict(lng_min=119.5, lng_max=122.0, lat_min=30.3, lat_max=32.5)


def ensure_schema(con) -> None:
    con.executescript(DDL)


def _edit(con, *, venue_id: str, kind: str, detail: dict, reviewer: str,
          note: str | None, now: str) -> dict:
    row = dict(
        id=f"vedit:{venue_id}:{kind}:{now}",
        venue_id=venue_id,
        kind=kind,
        detail=json.dumps(detail, ensure_ascii=False, sort_keys=True),
        reviewer=reviewer,
        note=note,
        edited_at=now,
    )
    con.execute(
        "INSERT OR REPLACE INTO venue_edits VALUES(:id,:venue_id,:kind,:detail,:reviewer,"
        ":note,:edited_at)",
        row,
    )
    return row


def event_usage(events: list[dict]) -> dict[str, int]:
    usage: dict[str, int] = {}
    for event in events:
        venue_id = event.get("venueId")
        if venue_id:
            usage[venue_id] = usage.get(venue_id, 0) + 1
    return usage


def duplicates(db_path: Path, alias_path: Path | None = None) -> list[dict]:
    snap = snapshot(db_path)
    usage = event_usage(snap["events"])
    already = {
        row.get("alias_id") for row in load_aliases(alias_path).get("aliases", [])
    }
    candidates = detect(snap["venues"], usage)
    # A pair already covered by an existing alias needs no further decision.
    return [c.as_dict() for c in candidates if c.alias_id not in already]


def coordinate_targets(db_path: Path) -> list[dict]:
    """Venues an event references but which have no usable coordinates yet."""
    snap = snapshot(db_path)
    usage = event_usage(snap["events"])
    rows = []
    for venue in snap["venues"]:
        if not usage.get(venue["id"]):
            continue
        coordinates = venue.get("coordinates")
        usable = bool(coordinates) and bool(coordinates.get("sourceUrl")) and bool(
            coordinates.get("system")
        )
        rows.append(
            {
                "id": venue["id"],
                "name": venue["name"],
                "address": venue.get("address"),
                "events": usage[venue["id"]],
                "has_coordinates": usable,
                "coordinates": coordinates,
            }
        )
    rows.sort(key=lambda r: (r["has_coordinates"], -r["events"], r["name"]))
    return rows


def resolve_chain(alias_id: str, alias_path: Path | None = None) -> str:
    """Follow aliases to their final target, refusing a cycle."""
    seen = {alias_id}
    alias_path = alias_path or default_alias_path()
    current = canonical_venue_id(alias_id, alias_path)
    while current != alias_id:
        if current in seen:
            raise ValueError(f"Venue alias cycle detected at {current}")
        seen.add(current)
        nxt = canonical_venue_id(current, alias_path)
        if nxt == current:
            return current
        current = nxt
    return current


def merge(db_path: Path, *, alias_id: str, canonical_id: str, reviewer: str,
          reason: str, evidence_url: str | None = None,
          alias_path: Path | None = None, revert: bool = False) -> dict:
    """Collapse one duplicate venue into another, on an explicit human decision."""
    if alias_id == canonical_id:
        raise ValueError("A venue cannot be merged into itself")
    if not reviewer.strip():
        raise ValueError("A merge must name the reviewer who decided it")

    alias_path = alias_path or default_alias_path()
    now = datetime.now(timezone.utc).isoformat()
    with connect(db_path) as con:
        ensure_schema(con)
        alias_row = con.execute(
            "SELECT payload FROM venues WHERE id=?", (alias_id,)
        ).fetchone()
        canonical_row = con.execute(
            "SELECT payload FROM venues WHERE id=?", (canonical_id,)
        ).fetchone()
        if canonical_row is None:
            raise ValueError(f"Unknown canonical venue: {canonical_id}")

        if revert:
            document = load_aliases(alias_path)
            kept = [
                row
                for row in document.get("aliases", [])
                if not (
                    row.get("alias_id") == alias_id
                    and row.get("canonical_id") == canonical_id
                )
            ]
            if len(kept) == len(document.get("aliases", [])):
                raise ValueError("No such alias to revert")
            document["aliases"] = kept
            alias_path.write_text(
                json.dumps(document, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            reset_cache()
            _edit(
                con,
                venue_id=alias_id,
                kind="merge_reverted",
                detail={"canonical_id": canonical_id},
                reviewer=reviewer,
                note=reason,
                now=now,
            )
            return {"reverted": True, "alias_id": alias_id, "canonical_id": canonical_id}

        alias_name = (
            json.loads(alias_row["payload"]).get("name") if alias_row else alias_id
        )
        name = json.loads(canonical_row["payload"]).get("name") or alias_name

        # Carry over anything the survivor lacks before the alias is recorded, because the
        # alias carries the canonical row and the row has to be the final one.
        #
        # The venue being merged away can be the only row holding a venue's verified
        # geometry: on the live data 苏州狮山大剧院 carried the AMap record while the
        # surviving 狮山大剧院 had six events and no coordinates. Deleting the alias row
        # without this transfer destroys the only copy of a coordinate, and a coordinate is
        # the one field that cannot be recovered by re-reading a source page.
        #
        # Only a field the canonical row is missing is filled, the value is copied verbatim,
        # and nothing is derived, guessed or overwritten.
        carried: list[str] = []
        if alias_row is not None:
            alias_payload = json.loads(alias_row["payload"])
            canonical_payload = json.loads(canonical_row["payload"])
            updated = dict(canonical_payload)
            for field in ("coordinates", "address"):
                if not canonical_payload.get(field) and alias_payload.get(field):
                    updated[field] = alias_payload[field]
                    carried.append(field)
            if carried:
                con.execute(
                    "UPDATE venues SET payload=? WHERE id=?",
                    (json.dumps(updated, ensure_ascii=False, sort_keys=True), canonical_id),
                )
                canonical_row = {"payload": json.dumps(updated, ensure_ascii=False)}

        # Record the alias first: it is the authority every later crawl reads. The canonical
        # row travels with it so the publish pipeline can resolve the id; without it the next
        # crawl refuses the alias with "canonical venue that is not declared".
        write_alias(
            alias_id=alias_id,
            canonical_id=canonical_id,
            name=name,
            reason=reason,
            evidence_url=evidence_url,
            path=alias_path,
            canonical_row=json.loads(canonical_row["payload"]),
        )
        reset_cache()

        events = con.execute(
            "SELECT id, payload FROM events WHERE venue=?", (alias_id,)
        ).fetchall()
        for event in events:
            payload = json.loads(event["payload"])
            payload["venueId"] = canonical_id
            con.execute(
                "UPDATE events SET venue=?, payload=? WHERE id=?",
                (
                    canonical_id,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    event["id"],
                ),
            )
            con.execute(
                "UPDATE crawler_unified_events SET normalized_json=? WHERE event_id=?",
                (
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    event["id"],
                ),
            )
            # The events now sit at a canonical venue, so their venue reference is settled.
            #
            # The stored claim must point at the venue the event actually references. Moving
            # the event row alone leaves its evidence pointing at the id that was just
            # deleted, so the claim and the event disagree for ever after. That is not a
            # cosmetic mismatch: every reader that cross-checks a stored claim against the
            # event it belongs to - the knowledge graph's venue edge, and the merge itself,
            # which reads this row to find what was approved - silently finds nothing.
            con.execute(
                "UPDATE crawler_evidence SET value=? "
                "WHERE event_id=? AND field_name='venue_id'",
                (json.dumps(canonical_id, ensure_ascii=False), event["id"]),
            )
            con.execute(
                "UPDATE evidence SET value=? "
                "WHERE entity_id=? AND field='venueId' AND value=?",
                (
                    json.dumps(canonical_id, ensure_ascii=False),
                    event["id"],
                    json.dumps(alias_id, ensure_ascii=False),
                ),
            )
            # Read back after the rewrite so the recorded decision names the value the event
            # now carries; recording the superseded id would leave the audit trail pointing
            # at the venue this merge just removed.
            claim = con.execute(
                "SELECT value FROM crawler_evidence WHERE event_id=? AND field_name='venue_id'",
                (event["id"],),
            ).fetchone()
            review.record(
                con,
                event_id=event["id"],
                field="venueId",
                decision=review.APPROVE,
                reviewed_value=json.loads(claim["value"]) if claim and claim["value"] else None,
                reviewer=reviewer,
                note=f"venue duplicate merged: {alias_name} -> {name}",
                decided_at=now,
            )

        observations = 0
        for row in con.execute(
            "SELECT source_id, item_key, normalized_json FROM crawler_observations"
        ).fetchall():
            try:
                document = json.loads(row["normalized_json"])
            except ValueError:
                continue
            if document.get("venue_id") != alias_id:
                continue
            document["venue_id"] = canonical_id
            con.execute(
                "UPDATE crawler_observations SET normalized_json=? "
                "WHERE source_id=? AND item_key=?",
                (
                    json.dumps(document, ensure_ascii=False, sort_keys=True),
                    row["source_id"],
                    row["item_key"],
                ),
            )
            observations += 1

        # The superseded row is now unreferenced; remove it so it cannot be merged again.
        remaining = con.execute(
            "SELECT COUNT(*) FROM events WHERE venue=?", (alias_id,)
        ).fetchone()[0]
        if remaining:
            raise ValueError(
                f"{remaining} events still reference {alias_id}; refusing to delete the row"
            )
        if alias_row is not None:
            con.execute("DELETE FROM venues WHERE id=?", (alias_id,))

        _edit(
            con,
            venue_id=canonical_id,
            kind="merge",
            detail={
                "alias_id": alias_id,
                "alias_name": alias_name,
                "events_moved": len(events),
                "observations_moved": observations,
                "evidence_url": evidence_url,
            },
            reviewer=reviewer,
            note=reason,
            now=now,
        )
    reset_cache()
    return {
        "merged": True,
        "alias_id": alias_id,
        "canonical_id": canonical_id,
        "events_moved": len(events),
        "observations_moved": observations,
    }


def set_coordinates(db_path: Path, *, venue_id: str, lng: float, lat: float,
                    source_url: str, reviewer: str, note: str | None = None,
                    system: str = "GCJ-02", status: str = "Verified") -> dict:
    """Record a human-supplied venue coordinate, with its provenance.

    ``status`` exists because not every coordinate deserves "Verified". A building entrance is
    a point and can be verified. A scenic area or an old town is a region, and the only
    coordinate AMap offers is one representative point inside it - 莲花岛's sits on its north
    side. Writing that as Verified would claim a precision the place does not have, so such a
    row is recorded as Needs Review and queued for a human instead.
    """
    if not reviewer.strip():
        raise ValueError("A coordinate must name the reviewer who checked it")
    if system != "GCJ-02":
        raise ValueError("Only GCJ-02 coordinates are accepted")
    if status not in ("Verified", "Needs Review"):
        raise ValueError("A coordinate status is Verified or Needs Review")
    if not (
        SUZHOU_BOUNDS["lng_min"] <= lng <= SUZHOU_BOUNDS["lng_max"]
        and SUZHOU_BOUNDS["lat_min"] <= lat <= SUZHOU_BOUNDS["lat_max"]
    ):
        raise ValueError(
            f"Coordinate {lng},{lat} is outside the Suzhou area; check for a typo"
        )
    url = (source_url or "").strip()
    if not url.startswith(("http://", "https://")):
        raise ValueError("A coordinate needs a source URL so it can be re-checked")

    now = datetime.now(timezone.utc).isoformat()
    with connect(db_path) as con:
        ensure_schema(con)
        row = con.execute("SELECT payload FROM venues WHERE id=?", (venue_id,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown venue: {venue_id}")
        payload = json.loads(row["payload"])
        payload["coordinates"] = {
            "lng": lng,
            "lat": lat,
            "system": system,
            "status": status,
            "sourceUrl": url,
        }
        con.execute(
            "UPDATE venues SET payload=? WHERE id=?",
            (json.dumps(payload, ensure_ascii=False, sort_keys=True), venue_id),
        )
        _edit(
            con,
            venue_id=venue_id,
            kind="coordinates",
            detail={"lng": lng, "lat": lat, "system": system, "sourceUrl": url},
            reviewer=reviewer,
            note=note,
            now=now,
        )
    return {"venue_id": venue_id, "coordinates": payload["coordinates"]}


def venue_edits(db_path: Path) -> list[dict]:
    with connect(db_path) as con:
        ensure_schema(con)
        return [
            dict(row)
            for row in con.execute(
                "SELECT * FROM venue_edits ORDER BY edited_at DESC"
            ).fetchall()
        ]


def apply_all_aliases(db_path: Path, alias_path: Path | None = None) -> int:
    """Re-assert every declared alias against the database (used after restoring a file)."""
    moved = 0
    for row in load_aliases(alias_path).get("aliases", []):
        alias_id = row.get("alias_id")
        canonical_id = row.get("canonical_id")
        if not alias_id or not canonical_id:
            continue
        with connect(db_path) as con:
            cur = con.execute(
                "UPDATE events SET venue=? WHERE venue=?", (canonical_id, alias_id)
            )
            moved += cur.rowcount
    reset_cache()
    return moved
