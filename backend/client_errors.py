"""Client-side error reports.

A blank white page is the worst possible failure mode for a tool this size: the person holding
the phone has no developer console, cannot see the exception, and has nothing to report but "it
does not open". That is exactly what happened with the knowledge-graph page on mobile.

Two mitigations, both here and in the frontend:

  1. An ErrorBoundary renders the message and stack instead of unmounting the tree, so a crash
     is readable on the device that crashed.
  2. window.onerror / onunhandledrejection POST a report here, so the failure is recorded in
     the database and can be read later from a desktop.

Stored, not alerted on: these are diagnostics, and a noisy alert would be ignored. The table is
bounded by pruning to the most recent rows so it cannot grow without limit.
"""
from __future__ import annotations

import json

# Keep the table small; this is a debugging aid, not an audit log.
KEEP_ROWS = 200

DDL = """
CREATE TABLE IF NOT EXISTS client_errors (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  occurred_at TEXT NOT NULL,
  message TEXT,
  source TEXT,
  stack TEXT,
  page TEXT,
  user_agent TEXT,
  viewport TEXT,
  extra TEXT
);
CREATE INDEX IF NOT EXISTS client_errors_time_idx ON client_errors(occurred_at);
"""


def ensure_schema(con) -> None:
    con.executescript(DDL)


def _clip(value, limit: int):
    if value is None:
        return None
    text = str(value)
    return text[:limit]


def record(con, *, report: dict, occurred_at: str) -> dict:
    """Store one report and prune old rows. Never raises on odd input.

    Everything is clipped and stringified because this endpoint is reachable by any client and
    a malformed report must not be able to poison the table or break the request.
    """
    ensure_schema(con)
    con.execute(
        """INSERT INTO client_errors(occurred_at,message,source,stack,page,user_agent,viewport,extra)
           VALUES(?,?,?,?,?,?,?,?)""",
        (
            occurred_at,
            _clip(report.get("message"), 500),
            _clip(report.get("source"), 300),
            _clip(report.get("stack"), 4000),
            _clip(report.get("page"), 300),
            _clip(report.get("userAgent"), 400),
            _clip(report.get("viewport"), 40),
            _clip(
                json.dumps(report.get("extra"), ensure_ascii=False)
                if report.get("extra") is not None
                else None,
                2000,
            ),
        ),
    )
    con.execute(
        "DELETE FROM client_errors WHERE id NOT IN "
        "(SELECT id FROM client_errors ORDER BY id DESC LIMIT ?)",
        (KEEP_ROWS,),
    )
    return {"stored": True}


def recent(con, limit: int = 50) -> list[dict]:
    ensure_schema(con)
    return [
        dict(row)
        for row in con.execute(
            "SELECT * FROM client_errors ORDER BY id DESC LIMIT ?",
            (max(1, min(limit, KEEP_ROWS)),),
        )
    ]
