"""Tenants: one hotel, its people, and its own private database.

## Why this exists

Everything the product holds today is public: events, venues, sources, evidence. A hotel's own
occupancy, rates, room-nights, channel mix and room-type mix are not public, and a hotel that
uploads them must be certain no other hotel can read them. That certainty cannot come from
remembering to add a WHERE clause, so the private data lives in a separate SQLite file per
tenant and the only way to reach it is the accessor in this module.

## The rule that makes it hold

**The tenant is never taken from the request.** It is resolved from the authenticated session
(``tenant_of_login``) and passed down as an argument. An endpoint that reads a ``tenant_id``
from a query string or a request body would let anyone switch tenants by editing a parameter,
and no other part of this design can compensate for that.

## Isolation

    data/tenants/<tenant_id>.sqlite3

One file per hotel. A hotel cannot read another's data because it cannot open another's file -
the guarantee is structural, not procedural. The cost is that cross-tenant aggregation would
have to open several files, which is why cross-hotel comparison is deliberately not built.

``tenant_id`` is validated against a strict pattern before it is ever used to build a path, so
a value like ``../../menduner`` cannot escape the tenant directory.

## What a tenant may hold

Only what the hotel chooses to upload. Nothing here is inferred, and nothing here is written
by the crawler: the public graph and the private ledger never share a file.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from backend.database import connect

# A tenant id becomes part of a filename, so it is restricted to characters that cannot form a
# path segment. This is the one validation that must never be relaxed.
TENANT_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,31}$")

ROLES = ("owner", "member")

DDL = """
CREATE TABLE IF NOT EXISTS tenants (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tenant_members (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  login TEXT NOT NULL,
  role TEXT NOT NULL,
  added_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS tenant_members_tenant_idx ON tenant_members(tenant_id);
CREATE UNIQUE INDEX IF NOT EXISTS tenant_members_login_idx ON tenant_members(login);
"""

# The private ledger. Metrics are stored by name so a hotel can upload the ones it has without
# the others becoming empty columns, and every row keeps who uploaded it and from which file -
# a number a manager cannot trace back to their own upload is worse than no number.
PRIVATE_DDL = """
CREATE TABLE IF NOT EXISTS private_metrics (
  id TEXT PRIMARY KEY,
  metric TEXT NOT NULL,
  period_start TEXT NOT NULL,
  period_end TEXT,
  channel TEXT,
  room_type TEXT,
  value REAL NOT NULL,
  uploaded_by TEXT NOT NULL,
  uploaded_at TEXT NOT NULL,
  source_file TEXT
);
CREATE INDEX IF NOT EXISTS private_metrics_metric_idx ON private_metrics(metric, period_start);
"""

# The metrics a hotel can supply. Deliberately a closed list: the product does not model price
# recommendations, and an unrecognised metric name would quietly become a column nobody reads.
METRICS = (
    "occupancy_pct",   # 入住率, 0-100
    "adr",             # 平均房价, the hotel's own currency
    "room_nights",     # 间夜
    "channel_share",   # 渠道占比, 0-100
    "room_type_share", # 房型结构占比, 0-100
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_schema(con) -> None:
    con.executescript(DDL)


def ensure_private_schema(con) -> None:
    con.executescript(PRIVATE_DDL)


def tenant_db_path(base_dir: Path, tenant_id: str) -> Path:
    """Where a tenant's private database lives, with the id validated first."""
    if not TENANT_ID.fullmatch(tenant_id or ""):
        raise ValueError(
            "Invalid tenant id: it becomes a filename, so only lower-case letters, digits "
            "and single hyphens are accepted"
        )
    return Path(base_dir) / "tenants" / f"{tenant_id}.sqlite3"


def create_tenant(db_path: Path, *, tenant_id: str, name: str) -> dict:
    """Register a hotel. The private database file is created on first write."""
    if not TENANT_ID.fullmatch(tenant_id or ""):
        raise ValueError("Invalid tenant id")
    if not (name or "").strip():
        raise ValueError("A tenant needs the hotel's name")
    with connect(db_path) as con:
        ensure_schema(con)
        if con.execute("SELECT 1 FROM tenants WHERE id=?", (tenant_id,)).fetchone():
            raise ValueError(f"Tenant already exists: {tenant_id}")
        con.execute(
            "INSERT INTO tenants(id, name, created_at) VALUES(?,?,?)",
            (tenant_id, name.strip(), now()),
        )
        return {"id": tenant_id, "name": name.strip()}


def add_member(db_path: Path, *, tenant_id: str, login: str, role: str = "member") -> dict:
    """Attach an account to a hotel.

    A hotel may have several accounts and they share one view of its data - the store manager
    and the staff all see the same ledger. Roles are recorded but not enforced yet: both roles
    can read everything in their own tenant, and neither can read another tenant.
    """
    if role not in ROLES:
        raise ValueError(f"role must be one of {', '.join(ROLES)}")
    who = (login or "").strip()
    if not who:
        raise ValueError("A member needs a login")
    with connect(db_path) as con:
        ensure_schema(con)
        if not con.execute("SELECT 1 FROM tenants WHERE id=?", (tenant_id,)).fetchone():
            raise ValueError(f"Unknown tenant: {tenant_id}")
        # One account belongs to one hotel, so a login cannot be used to read two ledgers.
        existing = con.execute(
            "SELECT tenant_id FROM tenant_members WHERE login=?", (who,)
        ).fetchone()
        if existing is not None:
            if existing["tenant_id"] == tenant_id:
                return {"tenant_id": tenant_id, "login": who, "role": role}
            raise ValueError(
                f"{who} already belongs to tenant {existing['tenant_id']}; "
                "an account cannot read two hotels' ledgers"
            )
        member_id = f"tm-{tenant_id}-{who}"
        con.execute(
            "INSERT INTO tenant_members(id, tenant_id, login, role, added_at) "
            "VALUES(?,?,?,?,?)",
            (member_id, tenant_id, who, role, now()),
        )
        return {"tenant_id": tenant_id, "login": who, "role": role}


def tenant_of_login(db_path: Path, login: str) -> str | None:
    """The tenant an authenticated login belongs to. Callers pass the result down; they never
    accept a tenant id from the client."""
    with connect(db_path) as con:
        ensure_schema(con)
        row = con.execute(
            "SELECT tenant_id FROM tenant_members WHERE login=?", ((login or "").strip(),)
        ).fetchone()
        return row["tenant_id"] if row else None


def members_of(db_path: Path, tenant_id: str) -> list[dict]:
    with connect(db_path) as con:
        ensure_schema(con)
        return [dict(r) for r in con.execute(
            "SELECT login, role, added_at FROM tenant_members WHERE tenant_id=? ORDER BY added_at",
            (tenant_id,),
        )]


def open_tenant_db(base_dir: Path, tenant_id: str) -> sqlite3.Connection:
    """The only way to reach a tenant's private data.

    Callers obtain ``tenant_id`` from the session, never from a request field. Handing out a
    connection rather than a path keeps the directory layout out of reach of business code.
    """
    path = tenant_db_path(base_dir, tenant_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    ensure_private_schema(con)
    return con


def record_metric(con, *, metric: str, period_start: str, value: float,
                  uploaded_by: str, period_end: str | None = None,
                  channel: str | None = None, room_type: str | None = None,
                  source_file: str | None = None) -> dict:
    """Store one private measurement in the tenant's own database."""
    if metric not in METRICS:
        raise ValueError(f"metric must be one of {', '.join(METRICS)}")
    try:
        datetime.strptime(period_start, "%Y-%m-%d")
    except (TypeError, ValueError):
        raise ValueError("period_start must be a YYYY-MM-DD date") from None
    if period_end is not None:
        try:
            datetime.strptime(period_end, "%Y-%m-%d")
        except (TypeError, ValueError):
            raise ValueError("period_end must be a YYYY-MM-DD date") from None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError("value must be a number")
    if not (uploaded_by or "").strip():
        raise ValueError("A private measurement must name who uploaded it")
    stamp = now()
    row_id = f"pm-{metric}-{period_start}-{stamp}"
    con.execute(
        "INSERT INTO private_metrics"
        "(id, metric, period_start, period_end, channel, room_type, value,"
        " uploaded_by, uploaded_at, source_file)"
        " VALUES(?,?,?,?,?,?,?,?,?,?)",
        (row_id, metric, period_start, period_end, channel, room_type, float(value),
         uploaded_by.strip(), stamp, source_file),
    )
    con.commit()
    return {"id": row_id, "metric": metric, "period_start": period_start, "value": value}


def read_metrics(con, *, metric: str | None = None) -> list[dict]:
    if metric is not None and metric not in METRICS:
        raise ValueError(f"metric must be one of {', '.join(METRICS)}")
    sql = "SELECT * FROM private_metrics"
    params: tuple = ()
    if metric:
        sql += " WHERE metric=?"
        params = (metric,)
    sql += " ORDER BY period_start"
    return [dict(r) for r in con.execute(sql, params)]
