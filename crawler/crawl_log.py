"""Per-run crawl log and consecutive-failure alerts.

Why this exists: a failing source was invisible. The crawl report said "Failed" and nothing
else happened — no record, no warning, no way to tell whether a source had been broken for one
run or for three weeks. Two tables fix that:

``crawl_runs``    one row per (source, run): when it started and finished, its status, how many
                  events it produced, how many were new, and why it failed.
``crawl_alerts``  a row raised when a source fails ``ALERT_THRESHOLD`` times in a row, and
                  resolved automatically when it succeeds again.

Deliberately simple: a table, not a monitoring system. The point is that "which source stopped
working, and when" is answerable with one query.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

# A single failure is usually a network blip; three in a row is a broken source.
ALERT_THRESHOLD = 3

# Statuses that mean the source contributed nothing usable.
FAILING = ("Failed",)

DDL = """
CREATE TABLE IF NOT EXISTS crawl_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT,
  source_id TEXT NOT NULL,
  source_name TEXT,
  started_at TEXT NOT NULL,
  finished_at TEXT NOT NULL,
  status TEXT NOT NULL,
  events_found INTEGER NOT NULL DEFAULT 0,
  events_new INTEGER NOT NULL DEFAULT 0,
  events_updated INTEGER NOT NULL DEFAULT 0,
  pages_collected INTEGER NOT NULL DEFAULT 0,
  failure_reason TEXT
);
CREATE INDEX IF NOT EXISTS crawl_runs_source_idx ON crawl_runs(source_id, finished_at);

CREATE TABLE IF NOT EXISTS crawl_alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id TEXT NOT NULL,
  source_name TEXT,
  raised_at TEXT NOT NULL,
  resolved_at TEXT,
  consecutive_failures INTEGER NOT NULL,
  reason TEXT
);
CREATE INDEX IF NOT EXISTS crawl_alerts_source_idx ON crawl_alerts(source_id, resolved_at);
"""


def ensure_schema(con) -> None:
    con.executescript(DDL)


def _representative_reason(attempt: dict) -> str | None:
    """The most useful one-line reason a source failed.

    ``error`` is sometimes a JSON blob of per-URL errors; the first message inside it is far
    more readable than the raw string, and the full text stays in the job report.
    """
    raw = attempt.get("error")
    if not raw:
        reasons = attempt.get("rejection_reasons") or []
        return str(reasons[0])[:500] if reasons else None
    text = str(raw)
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        return text[:500]
    if isinstance(parsed, list) and parsed:
        first = parsed[0]
        if isinstance(first, dict):
            return str(first.get("error"))[:500]
    if isinstance(parsed, dict):
        return str(parsed.get("error"))[:500]
    return text[:500]


def record_run(
    con,
    *,
    report: dict,
    started_at: str,
    finished_at: str,
    previous_counts: dict[str, int] | None = None,
) -> dict:
    """Write one crawl_runs row per source, then raise or resolve alerts.

    ``previous_counts`` maps source id to the event count before this run, which is how
    ``events_new`` is computed: the pipeline reports created/updated per JOB, not per source,
    so growth is attributed by comparing each source's stored events before and after.

    Returns a summary of what was raised and resolved.
    """
    ensure_schema(con)
    job_id = report.get("jobId")
    raised: list[dict] = []
    resolved: list[dict] = []

    for attempt in report.get("attempts", []):
        source_id = attempt.get("source") or "unknown"
        status = str(attempt.get("status") or "Unknown")
        accepted = int(attempt.get("accepted") or 0)
        pages = int(attempt.get("pagesCollected") or 0)
        reason = None if status == "Success" else _representative_reason(attempt)

        new = 0
        if previous_counts is not None:
            after = _event_count(con, report, source_id)
            new = max(0, after - previous_counts.get(source_id, after))

        con.execute(
            """INSERT INTO crawl_runs(job_id,source_id,source_name,started_at,finished_at,status,
                                      events_found,events_new,events_updated,pages_collected,
                                      failure_reason)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                job_id,
                source_id,
                _source_name(con, source_id),
                started_at,
                finished_at,
                status.upper(),
                accepted,
                new,
                accepted - new if accepted else 0,
                pages,
                reason,
            ),
        )

        if status in FAILING:
            alert = _raise_if_consecutive(con, source_id, report, finished_at, reason)
            if alert:
                raised.append(alert)
        else:
            settled = _resolve(con, source_id, finished_at)
            if settled:
                resolved.append(settled)

    return {"raised": raised, "resolved": resolved}


def _source_name(con, source_id: str) -> str | None:
    """The source's display name, or None.

    Deliberately failure-tolerant: the crawl log is diagnostics, so a missing table, a
    different schema version or an unregistered source must never be able to abort a crawl.
    The name is decoration; the id is the fact.
    """
    for query in (
        "SELECT name FROM sources WHERE id = ?",
        "SELECT payload FROM sources WHERE id = ?",
    ):
        try:
            row = con.execute(query, (source_id,)).fetchone()
        except Exception:
            continue
        if row is None:
            continue
        try:
            first = row[0]
        except (IndexError, TypeError):
            return None
        if not first:
            return None
        if str(first).lstrip().startswith("{"):
            try:
                return json.loads(first).get("name")
            except (ValueError, TypeError):
                return None
        return str(first)
    return None


def _event_count(con, report: dict, source_id: str) -> int:
    """How many events this source currently accounts for."""
    return con.execute(
        "SELECT COUNT(DISTINCT event_id) FROM crawler_observations WHERE source_id = ?",
        (source_id,),
    ).fetchone()[0]


def _consecutive_failures(con, source_id: str) -> int:
    """Count trailing failing runs for a source, newest first."""
    rows = con.execute(
        "SELECT status FROM crawl_runs WHERE source_id = ? ORDER BY id DESC LIMIT 20",
        (source_id,),
    ).fetchall()
    count = 0
    for row in rows:
        if row["status"] in FAILING or row["status"] == "FAILED":
            count += 1
        else:
            break
    return count


def _raise_if_consecutive(con, source_id: str, report: dict, now: str, reason: str | None) -> dict | None:
    """Raise an alert once a source has failed ``ALERT_THRESHOLD`` runs in a row."""
    failures = _consecutive_failures(con, source_id)
    if failures < ALERT_THRESHOLD:
        return None
    # One open alert per source: a source broken for a month should not add 30 rows.
    existing = con.execute(
        "SELECT id FROM crawl_alerts WHERE source_id = ? AND resolved_at IS NULL",
        (source_id,),
    ).fetchone()
    if existing:
        con.execute(
            "UPDATE crawl_alerts SET consecutive_failures = ?, reason = ? WHERE id = ?",
            (failures, reason, existing["id"]),
        )
        return None
    name = _source_name(con, source_id)
    con.execute(
        """INSERT INTO crawl_alerts(source_id,source_name,raised_at,consecutive_failures,reason)
           VALUES(?,?,?,?,?)""",
        (source_id, name, now, failures, reason),
    )
    return {
        "source_id": source_id,
        "source_name": name,
        "consecutive_failures": failures,
        "reason": reason,
    }


def _resolve(con, source_id: str, now: str) -> dict | None:
    row = con.execute(
        "SELECT id FROM crawl_alerts WHERE source_id = ? AND resolved_at IS NULL",
        (source_id,),
    ).fetchone()
    if row is None:
        return None
    con.execute("UPDATE crawl_alerts SET resolved_at = ? WHERE id = ?", (now, row["id"]))
    return {"source_id": source_id, "resolved_at": now}


def open_alerts(con) -> list[dict]:
    ensure_schema(con)
    return [
        dict(row)
        for row in con.execute(
            "SELECT * FROM crawl_alerts WHERE resolved_at IS NULL ORDER BY raised_at DESC"
        )
    ]


def recent_runs(con, limit: int = 100) -> list[dict]:
    ensure_schema(con)
    return [
        dict(row)
        for row in con.execute(
            "SELECT * FROM crawl_runs ORDER BY id DESC LIMIT ?", (limit,)
        )
    ]


def source_health(con) -> list[dict]:
    """Per source: last run, consecutive failures, whether an alert is open.

    Answers "which source stopped working, and when" in one call.
    """
    ensure_schema(con)
    rows = con.execute(
        """SELECT source_id,
                  MAX(finished_at) AS last_run,
                  COUNT(*) AS runs,
                  SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) AS failures
           FROM crawl_runs GROUP BY source_id ORDER BY source_id"""
    ).fetchall()
    out = []
    for row in rows:
        alert = con.execute(
            "SELECT raised_at, consecutive_failures FROM crawl_alerts "
            "WHERE source_id = ? AND resolved_at IS NULL ORDER BY id DESC LIMIT 1",
            (row["source_id"],),
        ).fetchone()
        last = con.execute(
            "SELECT status, events_found, failure_reason FROM crawl_runs "
            "WHERE source_id = ? ORDER BY id DESC LIMIT 1",
            (row["source_id"],),
        ).fetchone()
        out.append(
            {
                "source_id": row["source_id"],
                "source_name": _source_name(con, row["source_id"]),
                "runs": row["runs"],
                "failures": row["failures"],
                "last_run": row["last_run"],
                "last_status": last["status"] if last else None,
                "last_events_found": last["events_found"] if last else None,
                "last_failure_reason": last["failure_reason"] if last else None,
                "consecutive_failures": _consecutive_failures(con, row["source_id"]),
                "alert_raised_at": alert["raised_at"] if alert else None,
            }
        )
    return out
