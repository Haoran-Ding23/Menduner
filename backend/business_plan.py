"""The internal business-plan document: pricing assumptions, costs, pilot pipeline, milestones.

Why this is a JSON document in SQLite rather than tables: it is read and edited as a whole, by
one person, and every field is an assumption that changes together (a price change moves the
break-even number, a pipeline stage moves the forecast). Modelling that as ten small tables would
be ceremony without benefit. It lives in the database so it survives deploys and is not lost with
a browser cache.

It is NOT public data: GET and PUT are admin-only (backend/auth.py). The page that reads it is
internal, and the pricing / customer names in it must never be served to a customer account.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

KEY = "business-plan"
# Generous for a hand-edited document, small enough that it cannot be used as blob storage.
MAX_BYTES = 96_000

DDL = """
CREATE TABLE IF NOT EXISTS business_plan (
  key TEXT PRIMARY KEY,
  payload TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  updated_by TEXT NOT NULL
);
"""


def ensure_schema(con) -> None:
    con.executescript(DDL)


def load(con) -> dict:
    """The saved document, or an empty state that the client fills with its defaults."""
    ensure_schema(con)
    row = con.execute(
        "SELECT payload, updated_at, updated_by FROM business_plan WHERE key=?", (KEY,)
    ).fetchone()
    if row is None:
        return {"document": None, "updatedAt": None, "updatedBy": None}
    return {
        "document": json.loads(row["payload"]),
        "updatedAt": row["updated_at"],
        "updatedBy": row["updated_by"],
    }


def save(con, document, *, updated_by: str, now: str | None = None) -> dict:
    """Store the whole document. Validation is deliberately about shape and size, not schema.

    The client owns the fields; the server owns "is this a JSON object small enough to be a
    document". Pinning every field here would mean a migration for every new planning question.
    """
    if not isinstance(document, dict) or not document:
        raise ValueError("The business plan must be a non-empty JSON object")
    payload = json.dumps(document, ensure_ascii=False, sort_keys=True)
    if len(payload.encode("utf-8")) > MAX_BYTES:
        raise ValueError(f"The business plan is limited to {MAX_BYTES} bytes")
    ensure_schema(con)
    stamp = now or datetime.now(timezone.utc).isoformat()
    con.execute(
        "INSERT INTO business_plan(key, payload, updated_at, updated_by) VALUES(?,?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET payload=excluded.payload, "
        "updated_at=excluded.updated_at, updated_by=excluded.updated_by",
        (KEY, payload, stamp, updated_by),
    )
    return {"document": document, "updatedAt": stamp, "updatedBy": updated_by}
