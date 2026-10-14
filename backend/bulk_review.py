"""Check every factual field of one event at once.

A reviewer who has read one event's source page does not want to click ten times, and the
per-field flow made an event impossible to finish: a field that is genuinely absent from the
source (an organiser the page never states) stays ``Missing`` forever, and event-level status
requires every field to be settled.

So this approves the fields a human can actually judge, and answers with what remains:

  * a factual field with a value      -> the reviewer confirms the value;
  * a factual field with no value     -> the reviewer confirms the ABSENCE ("确认无此字段的值"),
    recorded under its own decision so the audit trail never claims a value was verified;
  * a conflicting field               -> never bulk-approved, left for individual resolution;
  * a derived / non-factual field     -> never touched, because no human can verify a reference
    id, a classification or a provenance URL by reading the page. ``pending:automatic`` records
    that they are deliberately excluded, which is different from "nobody looked".
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from backend.database import connect, snapshot
from crawler import review

# The `evidence` table (and therefore the review API) keys claims by the field names the
# frontend uses, not the crawler's internal names.
FACTUAL_FIELDS = (
    "name",
    "startDate",
    "endDate",
    "venueName",
    "location",
    "organizer",
)

# Derived or provenance fields: no human can verify a reference id, a classification or a
# response URL by reading the source page, so they are excluded rather than auto-approved.
NOT_APPLICABLE_FIELDS = (
    "venueId",
    "districtId",
    "category",
    "sourceUrl",
    "city",
    "fieldEvidence",
)

# Recorded on a "confirmed absent" decision, so it is never mistaken for verified content.
ABSENT_NOTE = "人工确认：来源未给出该字段的值"


def check_event(db_path: Path, event_id: str, reviewer: str) -> dict:
    """Settle every factual field of one event, attributable to a named reviewer."""
    if not reviewer.strip():
        raise ValueError("A review decision must name the reviewer")

    snap = snapshot(db_path)
    event = next((e for e in snap["events"] if e["id"] == event_id), None)
    if event is None:
        raise ValueError(f"Unknown event: {event_id}")

    claims = [row for row in snap["evidence"] if row["entityId"] == event_id]
    if not claims:
        raise ValueError(f"Event has no field evidence: {event_id}")

    now = datetime.now(timezone.utc).isoformat()
    approved: list[str] = []
    confirmed_absent: list[str] = []
    already: list[str] = []
    conflicts: list[str] = []
    excluded: list[str] = []

    with connect(db_path) as con:
        for claim in claims:
            field = claim["field"]
            status = claim["status"]
            if field not in FACTUAL_FIELDS:
                # Derived/provenance fields are excluded on purpose, and anything else is
                # reported so a new field type cannot be silently skipped.
                excluded.append(field)
                continue
            if status == "Conflicting":
                conflicts.append(field)
                continue
            if claim.get("decidedBy") == reviewer and status == "Verified":
                already.append(field)
                continue
            value = claim.get("value")
            if status == "Missing" or review.is_absent(value):
                # The reviewer records that the source states nothing here. The value stays
                # empty; only the absence is acknowledged, under its own decision kind.
                review.record(
                    con,
                    event_id=event_id,
                    field=field,
                    decision=review.ABSENT,
                    reviewed_value=None,
                    reviewer=reviewer.strip(),
                    note=ABSENT_NOTE,
                    decided_at=now,
                )
                confirmed_absent.append(field)
            else:
                review.record(
                    con,
                    event_id=event_id,
                    field=field,
                    decision=review.APPROVE,
                    reviewed_value=value,
                    reviewer=reviewer.strip(),
                    note="人工确认活动全部字段",
                    decided_at=now,
                )
                approved.append(field)

    return {
        "event_id": event_id,
        "approved": sorted(approved),
        "confirmed_absent": sorted(confirmed_absent),
        "already_verified": sorted(already),
        "conflicts_left_for_manual_review": sorted(conflicts),
        "not_applicable": sorted(excluded),
        "settled": len(approved) + len(confirmed_absent) + len(already),
        "needs_attention": len(conflicts),
    }
