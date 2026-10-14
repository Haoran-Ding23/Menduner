"""Durable human review decisions.

Why this is a separate table rather than an edit to ``evidence``:

``crawler/pipeline`` refreshes an event by DELETING and re-inserting its field evidence
on every crawl, because the page may have changed. Any human decision written directly
into an evidence row would therefore be destroyed by the next collection run. Human
review is the expensive, irreplaceable input, so it lives in its own table and is
re-applied as an overlay every time evidence is rebuilt.

A decision is bound to the *claim* it reviewed, not just to the field name:

    event_id + field + reviewed_value

If a later crawl extracts a different value for the same field, the old decision no
longer matches and the field returns to the human queue — a reviewer must never be
counted as having approved a value they never saw.
"""
from __future__ import annotations

import json
from hashlib import sha256

# Reviewer decisions a human can record.
APPROVE = "Verified"
REJECT = "Rejected"
CORRECT = "Corrected"
# The reviewer confirmed the SOURCE states no value for this field. Recorded separately from
# APPROVE so an audit trail never reads as if a value had been verified: nothing was verified,
# the absence was acknowledged. It stops applying the moment a value appears, because a
# reviewer cannot have approved a value they never saw.
ABSENT = "AbsentConfirmed"

DECISIONS = (APPROVE, REJECT, CORRECT, ABSENT)

ORIGIN_HUMAN = "human:review"

DDL = """
CREATE TABLE IF NOT EXISTS review_decisions (
  id TEXT PRIMARY KEY,
  event_id TEXT NOT NULL,
  field TEXT NOT NULL,
  decision TEXT NOT NULL,
  reviewed_value TEXT,
  corrected_value TEXT,
  reviewer TEXT NOT NULL,
  note TEXT,
  decided_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS review_decisions_event_idx ON review_decisions(event_id);
"""


def normalized(value) -> str:
    """Stable text form of a claim value, so two equal values compare equal."""
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return value
        value = parsed
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def decision_id(event_id: str, field: str) -> str:
    return "rev:" + sha256(f"{event_id}|{field}".encode()).hexdigest()[:32]


def ensure_schema(con) -> None:
    con.executescript(DDL)


def record(
    con,
    *,
    event_id: str,
    field: str,
    decision: str,
    reviewed_value=None,
    corrected_value=None,
    reviewer: str,
    note: str | None = None,
    decided_at: str,
) -> dict:
    """Upsert one review decision. The latest decision for a field wins."""
    if decision not in DECISIONS:
        raise ValueError(f"Unsupported review decision {decision!r}")
    if decision == CORRECT and corrected_value in (None, ""):
        raise ValueError("A correction must carry a replacement value")
    ensure_schema(con)
    row = dict(
        id=decision_id(event_id, field),
        event_id=event_id,
        field=field,
        decision=decision,
        reviewed_value=normalized(reviewed_value) if reviewed_value is not None else None,
        corrected_value=normalized(corrected_value) if corrected_value is not None else None,
        reviewer=reviewer,
        note=note,
        decided_at=decided_at,
    )
    con.execute(
        """INSERT INTO review_decisions VALUES(:id,:event_id,:field,:decision,:reviewed_value,
           :corrected_value,:reviewer,:note,:decided_at)
           ON CONFLICT(id) DO UPDATE SET
             decision=excluded.decision, reviewed_value=excluded.reviewed_value,
             corrected_value=excluded.corrected_value, reviewer=excluded.reviewer,
             note=excluded.note, decided_at=excluded.decided_at""",
        row,
    )
    return row


def decisions_for(con, event_id: str) -> dict[str, dict]:
    ensure_schema(con)
    return {
        r["field"]: dict(r)
        for r in con.execute(
            "SELECT * FROM review_decisions WHERE event_id=? ORDER BY decided_at", (event_id,)
        )
    }


def is_absent(value) -> bool:
    """True when a claim carries no value at all."""
    return value is None or value == "" or value == [] or value == {}


def resolve(decision: dict, current_value) -> tuple[str, object] | None:
    """Apply one decision to the current claim.

    Returns ``(status, value)`` when the decision still applies, or ``None`` when the
    underlying value changed and the review must be repeated.
    """
    if decision is None:
        return None
    kind = decision["decision"]
    if kind == ABSENT:
        # Only meaningful while the field is still empty: if a later crawl finds a value,
        # the reviewer's "the source says nothing" no longer describes the claim.
        return ("Verified", current_value) if is_absent(current_value) else None
    reviewed = decision.get("reviewed_value")
    if reviewed is not None and reviewed != normalized(current_value):
        return None
    if kind == APPROVE:
        return "Verified", current_value
    if kind == REJECT:
        return "Needs Review", current_value
    if kind == CORRECT:
        try:
            corrected = json.loads(decision["corrected_value"])
        except (ValueError, TypeError):
            corrected = decision["corrected_value"]
        return "Verified", corrected
    return None


def overlay(decisions: dict[str, dict], field: str, value, status: str) -> tuple[str, dict | None]:
    """Final status for a rebuilt claim, honouring a matching human decision.

    ``decisions`` is the preloaded mapping from :func:`decisions_for` for one event, so a
    caller rebuilding ten fields does not re-query the table ten times.
    """
    decision = decisions.get(field)
    applied = resolve(decision, value)
    if applied is None:
        return status, None
    return applied[0], decision
