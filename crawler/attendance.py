"""Attendance records: the measurement this project accumulates but never predicts.

## Why this table exists

The interviewed operations lead asked for 人数 - how many people an event brings - and this
system cannot supply it. Nothing here guesses: it stores measurements as they are found, so
that a dataset can exist later. One row is one measurement of one event by one source.

## Four decisions that shape the schema

**1. Many rows per event, never one merged number.** An event will be measured more than
once and the measurements disagree: a ticketing figure, a news figure and a hotel's own
room-night count are three different numbers about one night. Collapsing them would force a
choice into the data. Keeping them apart keeps the disagreement visible, which is itself what
a model needs to learn from.

**2. ``event_id`` may be NULL.** Requiring a link to our events table would mean only the
events we crawled could ever be measured, and the project holds upcoming events rather than
history - so the training set would be biased toward exactly the events we already have and
empty of everything else. An attendance row therefore identifies its subject by name and date
alone, and links to an event only when one matches. Historical measurements can therefore be
recorded today.

**3. The number's scope is recorded, not assumed.** 5000 can mean one day's attendance, a
whole run's total, a peak day, or tickets sold. Numbers with different scopes must never be
mixed in one training set, so ``measure`` states which one it is and validation rejects a
value whose scope cannot be established.

**4. How the number was obtained is recorded.** An official announcement and a figure we
derived from venue capacity are not the same kind of evidence, so ``method`` separates
``official`` from ``capacity_estimate`` from ``inference``. Without it the dataset would
quietly treat a guess as a measurement.

## What is deliberately absent

No price, no revenue, no occupancy prediction, and no model output. This table stores what
was observed. Anything computed from it is computed elsewhere and is not written back here,
so a derived value can never be mistaken for a measurement.

## Provenance

The project's rule is that a value must be traceable, so ``source_url`` is expected for every
method that reads a public page. It is nullable because a measurement can legitimately come
from a conversation or a venue's own staff, and ``collected_by`` records who obtained it. A
number with no URL and no named collector would be unattributable, and validation refuses it.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

DDL = """
CREATE TABLE IF NOT EXISTS attendance_records (
  id TEXT PRIMARY KEY,
  event_id TEXT REFERENCES events(id) ON DELETE SET NULL,
  subject_name TEXT NOT NULL,
  observed_on TEXT NOT NULL,
  measure TEXT NOT NULL,
  count INTEGER NOT NULL,
  method TEXT NOT NULL,
  confidence TEXT NOT NULL,
  source_type TEXT NOT NULL,
  source_name TEXT,
  source_url TEXT,
  source_text TEXT,
  venue_capacity INTEGER,
  collected_by TEXT NOT NULL,
  collected_at TEXT NOT NULL,
  note TEXT
);
CREATE INDEX IF NOT EXISTS attendance_event_idx ON attendance_records(event_id);
CREATE INDEX IF NOT EXISTS attendance_date_idx ON attendance_records(observed_on);
CREATE INDEX IF NOT EXISTS attendance_subject_idx ON attendance_records(subject_name);
"""

# What the number counts. Numbers of different scopes are not comparable, so this is required
# rather than inferred from the text around them.
MEASURES = (
    "single_day",     # attendance on one specific day
    "full_run",       # total across the whole run of the event
    "peak_day",       # the busiest single day
    "tickets_sold",   # tickets issued, which is not the same as people who came
    "rooms_booked",   # hotel room-nights attributed to the event
)

# How the number was obtained. Ordered from strongest evidence to weakest so a reader can see
# what kind of claim they are looking at without following the URL.
METHODS = (
    "official",           # published by the organiser, venue or a government body
    "ticketing",          # published by a ticketing platform, usually tickets issued
    "news",               # stated in reporting, often quoting an official
    "field_observation",  # counted by a person on site
    "capacity_estimate",  # derived from the venue's capacity and an attendance assumption
    "inference",          # reasoned from other signals; weakest
)
# The last two are not measurements of attendance, they are estimates of it. Kept in the
# dataset so they can be used, and labelled so they can be excluded.
ESTIMATED_METHODS = frozenset({"capacity_estimate", "inference"})

CONFIDENCE = ("high", "medium", "low")

SOURCE_TYPES = ("official_site", "ticketing_platform", "news_media", "social_media",
                "venue_staff", "person_on_site", "internal_estimate")


def ensure_schema(con) -> None:
    con.executescript(DDL)


def record_id(subject_name: str, observed_on: str, count: int, method: str,
              source_url: str | None) -> str:
    """Stable identity for one measurement, so re-recording the same one is refused.

    Two genuinely different measurements of the same event differ in at least one of date,
    count, method or source, so this key does not collapse them.
    """
    import hashlib
    key = f"{subject_name}|{observed_on}|{count}|{method}|{source_url or ''}"
    return "att:" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


def record(con, *, subject_name: str, observed_on: str, count: int, measure: str,
           method: str, source_type: str, collected_by: str,
           event_id: str | None = None, confidence: str = "medium",
           source_name: str | None = None, source_url: str | None = None,
           source_text: str | None = None, venue_capacity: int | None = None,
           note: str | None = None, collected_at: str | None = None) -> dict:
    """Record one attendance measurement.

    Refuses rather than guesses: a count with no scope, a number with no attribution, and a
    capacity-derived figure presented as an official measurement are all rejected here, at the
    point of entry, because a bad row in this table becomes a bad training example later and
    nothing downstream can tell.
    """
    if not (subject_name or "").strip():
        raise ValueError("An attendance record needs the event's name")
    if event_id is not None:
        found = con.execute("SELECT 1 FROM events WHERE id=?", (event_id,)).fetchone()
        if found is None:
            raise ValueError(f"Unknown event: {event_id}")
    try:
        datetime.strptime(observed_on, "%Y-%m-%d")
    except (TypeError, ValueError):
        raise ValueError("observed_on must be a YYYY-MM-DD date") from None
    if measure not in MEASURES:
        raise ValueError(f"measure must be one of {', '.join(MEASURES)}")
    if method not in METHODS:
        raise ValueError(f"method must be one of {', '.join(METHODS)}")
    if confidence not in CONFIDENCE:
        raise ValueError(f"confidence must be one of {', '.join(CONFIDENCE)}")
    if source_type not in SOURCE_TYPES:
        raise ValueError(f"source_type must be one of {', '.join(SOURCE_TYPES)}")
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        raise ValueError("count must be a non-negative whole number")
    if venue_capacity is not None:
        if not isinstance(venue_capacity, int) or isinstance(venue_capacity, bool):
            raise ValueError("venue_capacity must be a whole number")
        if venue_capacity <= 0:
            raise ValueError("venue_capacity must be positive")
    # A measurement has to be attributable. A public page gives a URL; a person gives a name.
    url = (source_url or "").strip() or None
    if url is not None and not url.startswith(("http://", "https://")):
        raise ValueError("source_url must be an http(s) address")
    named = bool((source_name or "").strip())
    if url is None and not named:
        raise ValueError(
            "An attendance record needs either a source URL or a named source, "
            "otherwise the number cannot be traced back to anything"
        )
    if not (collected_by or "").strip():
        raise ValueError("An attendance record must name who collected it")
    # A figure derived from capacity must say so; presenting it as an official count would
    # turn an assumption into a measurement.
    if method in ESTIMATED_METHODS and confidence == "high":
        raise ValueError(
            f"A {method} figure cannot be recorded as high confidence; it estimates "
            "attendance rather than measuring it"
        )

    now = collected_at or datetime.now(timezone.utc).isoformat()
    row_id = record_id(subject_name.strip(), observed_on, count, method, url)
    existing = con.execute("SELECT 1 FROM attendance_records WHERE id=?", (row_id,)).fetchone()
    if existing is not None:
        raise ValueError("This measurement is already recorded")

    con.execute(
        "INSERT INTO attendance_records"
        "(id, event_id, subject_name, observed_on, measure, count, method, confidence,"
        " source_type, source_name, source_url, source_text, venue_capacity,"
        " collected_by, collected_at, note)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (row_id, event_id, subject_name.strip(), observed_on, measure, count, method,
         confidence, source_type, (source_name or "").strip() or None, url,
         (source_text or "").strip() or None, venue_capacity,
         collected_by.strip(), now, (note or "").strip() or None),
    )
    return {"id": row_id, "subject_name": subject_name, "observed_on": observed_on,
            "count": count, "measure": measure, "method": method, "confidence": confidence}


def for_event(con, event_id: str) -> list[dict]:
    """Every measurement of one event, so disagreements stay visible side by side."""
    rows = con.execute(
        "SELECT * FROM attendance_records WHERE event_id=? ORDER BY observed_on, count",
        (event_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def export_training_rows(con, *, measured_only: bool = False) -> list[dict]:
    """The records as training rows, joined to the event and venue where a link exists.

    ``measured_only`` drops the capacity-derived and inferred rows. The default keeps
    everything, because deciding what a model may learn from is the model's business; the
    flag exists so that choice can be made explicitly rather than by accident.
    """
    clauses = ["1=1"]
    if measured_only:
        placeholders = ",".join("?" for _ in ESTIMATED_METHODS)
        clauses.append(f"a.method NOT IN ({placeholders})")
    params = tuple(sorted(ESTIMATED_METHODS)) if measured_only else ()
    sql = (
        "SELECT a.id, a.event_id, a.subject_name, a.observed_on, a.measure, a.count,"
        " a.method, a.confidence, a.source_type, a.source_name, a.source_url,"
        " a.venue_capacity, a.collected_by, a.collected_at, a.note,"
        " e.name AS event_name, e.category AS event_category,"
        " e.startDate AS event_start, e.endDate AS event_end, e.venue AS venue_id,"
        " v.payload AS venue_payload"
        " FROM attendance_records a"
        " LEFT JOIN events e ON e.id = a.event_id"
        " LEFT JOIN venues v ON v.id = e.venue"
        " WHERE " + " AND ".join(clauses) +
        " ORDER BY a.observed_on, a.subject_name"
    )
    out = []
    for row in con.execute(sql, params):
        item = dict(row)
        payload = item.pop("venue_payload", None)
        venue_name = None
        if payload:
            try:
                venue_name = json.loads(payload).get("name")
            except (TypeError, ValueError):
                venue_name = None
        item["venue_name"] = venue_name
        # The utilisation a model can actually use, computed only when both halves exist.
        capacity = item.get("venue_capacity")
        if capacity:
            item["utilisation"] = round(item["count"] / capacity, 4)
        else:
            item["utilisation"] = None
        out.append(item)
    return out


def summary(con) -> dict:
    """What the dataset currently holds, so its coverage is never overstated.

    The dataset starts empty and grows one measurement at a time. Reporting the span and the
    method mix here means a model trained on it can state what it was trained on instead of
    assuming the data was always there.
    """
    total = con.execute("SELECT COUNT(*) FROM attendance_records").fetchone()[0]
    linked = con.execute(
        "SELECT COUNT(*) FROM attendance_records WHERE event_id IS NOT NULL"
    ).fetchone()[0]
    with_url = con.execute(
        "SELECT COUNT(*) FROM attendance_records WHERE source_url IS NOT NULL"
    ).fetchone()[0]
    span = con.execute(
        "SELECT MIN(observed_on), MAX(observed_on) FROM attendance_records"
    ).fetchone()
    by_method = {
        r["method"]: r["n"] for r in con.execute(
            "SELECT method, COUNT(*) n FROM attendance_records GROUP BY method")
    }
    by_measure = {
        r["measure"]: r["n"] for r in con.execute(
            "SELECT measure, COUNT(*) n FROM attendance_records GROUP BY measure")
    }
    return {
        "total": total,
        "linked_to_event": linked,
        "unlinked": total - linked,
        "with_source_url": with_url,
        "estimated": sum(by_method.get(m, 0) for m in ESTIMATED_METHODS),
        "first_observed_on": span[0] if span else None,
        "last_observed_on": span[1] if span else None,
        "by_method": by_method,
        "by_measure": by_measure,
        # Explicit, because an empty dataset is the honest starting state and a reader should
        # not have to infer it from a zero.
        "status": "empty" if total == 0 else "collecting",
    }


def dataset_start() -> str:
    """The day this table began collecting, recorded so coverage is never overstated."""
    return date(2026, 10, 15).isoformat()
