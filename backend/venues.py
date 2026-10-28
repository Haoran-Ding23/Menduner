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
        # coordinates 有两种写法：结构化 dict（带 sourceUrl/system），或 [lng, lat] 数组。
        # 数组形式下没有来源信息，不能算「可用坐标」，但也不能因此抛异常把整页弄挂。
        coordinates_meta = coordinates if isinstance(coordinates, dict) else {}
        usable = bool(coordinates_meta.get("sourceUrl")) and bool(coordinates_meta.get("system"))
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


def _served_claim_rows(con, *, event_id: str, field: str) -> list:
    return con.execute(
        "SELECT id, value, payload FROM evidence WHERE entity_id=? AND field=?",
        (event_id, field),
    ).fetchall()


def _rewrite_served_claim(con, *, row_id: str, value, payload: dict | None = None) -> None:
    """Write a served claim's value into BOTH the column and the payload.

    ``snapshot()`` serves ``evidence.payload`` — the value column is a convenience for SQL.
    Rewriting only the column (which is what the merge did until 2026-10-18) leaves the API
    serving the deleted venue id, and every reader that cross-checks a claim against the event
    it belongs to finds nothing: the event says the canonical venue, the claim still says the
    one the merge removed.
    """
    if payload is None:
        existing = con.execute(
            "SELECT payload FROM evidence WHERE id=?", (row_id,)
        ).fetchone()
        try:
            payload = json.loads(existing["payload"]) if existing and existing["payload"] else {}
        except ValueError:
            payload = {}
    payload = dict(payload)
    payload["value"] = value
    con.execute(
        "UPDATE evidence SET value=?, payload=? WHERE id=?",
        (
            json.dumps(value, ensure_ascii=False),
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            row_id,
        ),
    )


def _latest_merge_undo(con, *, alias_id: str, canonical_id: str) -> dict | None:
    """The restore data recorded by the merge that produced this alias, if any.

    Merges made before the undo record existed have none, and an undo that silently returns
    success without putting the data back is worse than refusing: it is the exact complaint
    that produced this code.
    """
    rows = con.execute(
        "SELECT detail FROM venue_edits WHERE venue_id=? AND kind='merge' "
        "ORDER BY edited_at DESC",
        (canonical_id,),
    ).fetchall()
    for row in rows:
        try:
            detail = json.loads(row["detail"])
        except ValueError:
            continue
        if detail.get("alias_id") != alias_id:
            continue
        undo = detail.get("undo")
        if isinstance(undo, dict):
            return undo
    return None


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
            undo = _latest_merge_undo(con, alias_id=alias_id, canonical_id=canonical_id)
            if undo is None:
                raise ValueError(
                    f"{alias_id} → {canonical_id} 的这次合并没有留下可恢复的数据"
                    "（撤销能力是 2026-10-18 才加的）。不能假装撤销成功："
                    "请核对 crawler_raw_items / crawler_observations 后重建，"
                    "或从数据库备份恢复。"
                )
            if con.execute("SELECT 1 FROM venues WHERE id=?", (canonical_id,)).fetchone() is None:
                raise ValueError(
                    f"合并目标 {canonical_id} 已不存在（可能又被合并），无法撤销"
                )
            if con.execute("SELECT 1 FROM venues WHERE id=?", (alias_id,)).fetchone() is not None:
                raise ValueError(
                    f"{alias_id} 已经存在一行场馆记录，撤销会覆盖真实数据；请先核对"
                )
            alias_payload = undo.get("alias_payload")
            if not isinstance(alias_payload, dict) or not alias_payload.get("name"):
                raise ValueError(
                    f"这次合并没有记录 {alias_id} 被删除时的场馆行，无法恢复"
                )
            con.execute(
                "INSERT INTO venues(id, payload) VALUES(?, ?)",
                (alias_id, json.dumps(alias_payload, ensure_ascii=False, sort_keys=True)),
            )
            # The merge may have lent the survivor a field the alias row alone held (a
            # coordinate, an address). Give it back only while the survivor still carries
            # exactly that value: if it was refined afterwards, that later human edit wins.
            carried = undo.get("carried")
            carried_removed: list[str] = []
            carried_kept: list[str] = []
            if isinstance(carried, dict) and carried:
                survivor_row = con.execute(
                    "SELECT payload FROM venues WHERE id=?", (canonical_id,)
                ).fetchone()
                survivor_payload = json.loads(survivor_row["payload"])
                for field, value in carried.items():
                    if survivor_payload.get(field) == value:
                        survivor_payload.pop(field, None)
                        carried_removed.append(field)
                    else:
                        carried_kept.append(field)
                con.execute(
                    "UPDATE venues SET payload=? WHERE id=?",
                    (
                        json.dumps(survivor_payload, ensure_ascii=False, sort_keys=True),
                        canonical_id,
                    ),
                )

            restored_events = 0
            for item in undo.get("events", []):
                event_id = item.get("event_id")
                if not event_id:
                    continue
                event_row = con.execute(
                    "SELECT payload FROM events WHERE id=?", (event_id,)
                ).fetchone()
                if event_row is None:
                    continue
                payload = json.loads(event_row["payload"])
                payload["venueId"] = alias_id
                con.execute(
                    "UPDATE events SET venue=?, payload=? WHERE id=?",
                    (
                        alias_id,
                        json.dumps(payload, ensure_ascii=False, sort_keys=True),
                        event_id,
                    ),
                )
                con.execute(
                    "UPDATE crawler_unified_events SET normalized_json=? WHERE event_id=?",
                    (json.dumps(payload, ensure_ascii=False, sort_keys=True), event_id),
                )
                claim = item.get("stored_claim") or {}
                if "value_before" in claim:
                    con.execute(
                        "UPDATE crawler_evidence SET value=? "
                        "WHERE event_id=? AND field_name='venue_id'",
                        (claim["value_before"], event_id),
                    )
                served = item.get("served_claim") or {}
                if served.get("id"):
                    previous = served.get("payload")
                    _rewrite_served_claim(
                        con,
                        row_id=served["id"],
                        value=json.loads(served["value"]) if served.get("value") else None,
                        payload=json.loads(previous) if isinstance(previous, str) else None,
                    )
                decision_id = item.get("decision_id")
                if decision_id:
                    con.execute(
                        "DELETE FROM review_decisions WHERE id=?", (decision_id,)
                    )
                restored_events += 1

            restored_observations = 0
            for item in undo.get("observations", []):
                source_id = item.get("source_id")
                item_key = item.get("item_key")
                if not source_id or not item_key:
                    continue
                row = con.execute(
                    "SELECT normalized_json FROM crawler_observations "
                    "WHERE source_id=? AND item_key=?",
                    (source_id, item_key),
                ).fetchone()
                if row is None:
                    continue
                try:
                    document_row = json.loads(row["normalized_json"])
                except ValueError:
                    continue
                if document_row.get("venue_id") != canonical_id:
                    # Rewritten again since the merge; do not clobber a later decision.
                    continue
                document_row["venue_id"] = alias_id
                con.execute(
                    "UPDATE crawler_observations SET normalized_json=? "
                    "WHERE source_id=? AND item_key=?",
                    (
                        json.dumps(document_row, ensure_ascii=False, sort_keys=True),
                        source_id,
                        item_key,
                    ),
                )
                restored_observations += 1

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
                detail={
                    "canonical_id": canonical_id,
                    "restored_events": restored_events,
                    "restored_observations": restored_observations,
                },
                reviewer=reviewer,
                note=reason,
                now=now,
            )
            return {
                "reverted": True,
                "alias_id": alias_id,
                "canonical_id": canonical_id,
                "restored": {
                    "venue": True,
                    "carried_removed": carried_removed,
                    "carried_kept": carried_kept,
                    "events": restored_events,
                    "observations": restored_observations,
                },
            }

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
        carried: dict[str, object] = {}
        if alias_row is not None:
            alias_payload = json.loads(alias_row["payload"])
            canonical_payload = json.loads(canonical_row["payload"])
            updated = dict(canonical_payload)
            for field in ("coordinates", "address"):
                if not canonical_payload.get(field) and alias_payload.get(field):
                    updated[field] = alias_payload[field]
                    carried[field] = alias_payload[field]
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
        moved_events: list[dict] = []
        for event in events:
            payload = json.loads(event["payload"])
            payload["venueId"] = canonical_id
            # Capture what a later undo has to put back, before anything is overwritten.
            served_before = _served_claim_rows(con, event_id=event["id"], field="venueId")
            stored_before = con.execute(
                "SELECT value FROM crawler_evidence "
                "WHERE event_id=? AND field_name='venue_id'",
                (event["id"],),
            ).fetchone()
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
            # ... and the served claim carries the value in its payload, which is what the API
            # reads. Rewriting the column alone is the bug the reviewer found on 2026-10-18:
            # the event pointed at the survivor while its evidence still named the row the
            # merge had just deleted.
            for served in served_before:
                _rewrite_served_claim(
                    con,
                    row_id=served["id"],
                    value=canonical_id,
                    payload=json.loads(served["payload"]) if served["payload"] else {},
                )
            # Read back after the rewrite so the recorded decision names the value the event
            # now carries; recording the superseded id would leave the audit trail pointing
            # at the venue this merge just removed.
            claim = con.execute(
                "SELECT value FROM crawler_evidence WHERE event_id=? AND field_name='venue_id'",
                (event["id"],),
            ).fetchone()
            recorded = review.record(
                con,
                event_id=event["id"],
                field="venueId",
                decision=review.APPROVE,
                reviewed_value=json.loads(claim["value"]) if claim and claim["value"] else None,
                reviewer=reviewer,
                note=f"venue duplicate merged: {alias_name} -> {name}",
                decided_at=now,
            )
            moved_events.append(
                {
                    "event_id": event["id"],
                    "stored_claim": {
                        "value_before": stored_before["value"] if stored_before else None
                    },
                    "served_claim": (
                        {
                            "id": served_before[0]["id"],
                            "value": served_before[0]["value"],
                            "payload": served_before[0]["payload"],
                        }
                        if served_before
                        else None
                    ),
                    "decision_id": recorded["id"],
                }
            )

        observations = 0
        moved_observations: list[dict] = []
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
            moved_observations.append(
                {"source_id": row["source_id"], "item_key": row["item_key"]}
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
                # Everything a revert needs. Without it "撤销成功" was a lie: the venue row,
                # the event references and the claims stayed gone.
                "undo": {
                    "alias_payload": json.loads(alias_row["payload"]) if alias_row else None,
                    "carried": carried,
                    "events": moved_events,
                    "observations": moved_observations,
                },
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
