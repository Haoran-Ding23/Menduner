"""Customer accounts, invite-code trials and offline (对公转账) activation.

The distinction from the internal accounts in backend/auth.py matters: those are HTTP-Basic
operator logins (nginx validates the password; the backend maps the login to a role). These are
PRODUCT accounts owned by customers: they exist in SQLite, authenticate with a password hash and a
signed session cookie, and carry the plan that decides which paid workflow is unlocked.

Flow, in the order a customer experiences it:
  1. an operator creates an invite code (plan + trial days + max uses) in the review console;
  2. the customer registers with that code -> account on a trial (4 weeks by default);
  3. when the trial is over, the customer files a payment request (offline: bank transfer);
  4. the operator confirms the money arrived; the subscription end date is extended by calendar
     months and the account becomes active;
  5. the server derives the effective plan from the dates on every request -- a trial that ran out
     means ``free`` even if the account row still says ``pro``.

Payment is deliberately offline: there is no payment gateway, no card data, no fake "paid" state.
An order is pending until an operator confirms it, and confirming is the only thing that grants a
paid period.
"""
from __future__ import annotations

import calendar
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

# Prices live here because the server computes the order amount; the frontend only displays it.
# Per hotel per month, matching the customer plans page. Enterprise is cheaper per hotel because
# it is billed across a multi-hotel portfolio.
PLAN_PRICES = {"pro": 980, "enterprise": 780}
PLAN_NAMES = {"pro": "专业版", "enterprise": "企业版"}
SESSION_COOKIE = "menduner_session"
SESSION_DAYS = 14
TRIAL_DAYS_DEFAULT = 28
LOGIN_RE = re.compile(r"^[A-Za-z0-9._-]{3,32}$")
INVITE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
PASSWORD_ITERATIONS = 200_000
MAX_LOGIN_FAILURES = 8
LOGIN_WINDOW_SECONDS = 900

DDL = """
CREATE TABLE IF NOT EXISTS customer_accounts (
  id TEXT PRIMARY KEY,
  login TEXT NOT NULL UNIQUE COLLATE NOCASE,
  name TEXT NOT NULL,
  hotel TEXT,
  password_hash TEXT NOT NULL,
  plan TEXT NOT NULL DEFAULT 'pro',
  trial_ends_at TEXT,
  subscription_ends_at TEXT,
  invite_code TEXT,
  suspended INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  last_login_at TEXT
);
CREATE TABLE IF NOT EXISTS customer_sessions (
  token_hash TEXT PRIMARY KEY,
  account_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS invite_codes (
  code TEXT PRIMARY KEY,
  plan TEXT NOT NULL,
  trial_days INTEGER NOT NULL,
  max_uses INTEGER NOT NULL DEFAULT 1,
  used_count INTEGER NOT NULL DEFAULT 0,
  note TEXT,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT
);
CREATE TABLE IF NOT EXISTS customer_orders (
  id TEXT PRIMARY KEY,
  account_id TEXT NOT NULL,
  plan TEXT NOT NULL,
  months INTEGER NOT NULL,
  amount_cny INTEGER NOT NULL,
  note TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT NOT NULL,
  confirmed_at TEXT,
  confirmed_by TEXT
);
"""


def ensure_schema(con) -> None:
    con.executescript(DDL)


# --- time helpers -------------------------------------------------------------
def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


def parse(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def add_months(moment: datetime, months: int) -> datetime:
    """Calendar-month arithmetic (a 1-month subscription bought on 31 Jan ends 28 Feb)."""
    month = moment.month - 1 + months
    year = moment.year + month // 12
    month = month % 12 + 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


# --- passwords and sessions ---------------------------------------------------
def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"),
                                 PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt, expected = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"),
                                    int(iterations))
        return hmac.compare_digest(digest.hex(), expected)
    except ValueError:
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(con, account_id: str) -> str:
    token = secrets.token_urlsafe(32)
    stamp = now_utc()
    con.execute(
        "INSERT INTO customer_sessions(token_hash, account_id, created_at, expires_at) "
        "VALUES(?,?,?,?)",
        (token_hash(token), account_id, iso(stamp), iso(stamp + timedelta(days=SESSION_DAYS))),
    )
    return token


def session_account(con, token: str | None) -> dict | None:
    if not token:
        return None
    row = con.execute(
        "SELECT a.* FROM customer_sessions s JOIN customer_accounts a ON a.id = s.account_id "
        "WHERE s.token_hash=? AND s.expires_at > ?",
        (token_hash(token), iso(now_utc())),
    ).fetchone()
    return dict(row) if row else None


def delete_session(con, token: str | None) -> None:
    if not token:
        return
    con.execute("DELETE FROM customer_sessions WHERE token_hash=?", (token_hash(token),))


# --- entitlements -------------------------------------------------------------
def entitlements(account: dict | None, now: datetime | None = None) -> dict:
    """The effective plan, derived from dates rather than trusted from a column.

    This is the only place the rest of the backend asks "may this customer use a paid workflow",
    so an expired trial cannot keep a paid feature alive by leaving ``plan='pro'`` in the row.
    """
    stamp = now or now_utc()
    if not account:
        return {"plan": "free", "status": "anonymous", "expiresAt": None,
                "trialEndsAt": None, "subscriptionEndsAt": None}
    if account.get("suspended"):
        return {"plan": "free", "status": "suspended", "expiresAt": None,
                "trialEndsAt": account.get("trial_ends_at"),
                "subscriptionEndsAt": account.get("subscription_ends_at")}
    trial_ends = parse(account.get("trial_ends_at"))
    subscription_ends = parse(account.get("subscription_ends_at"))
    if subscription_ends and stamp < subscription_ends:
        return {"plan": account["plan"], "status": "active", "expiresAt": iso(subscription_ends),
                "trialEndsAt": account.get("trial_ends_at"),
                "subscriptionEndsAt": account.get("subscription_ends_at")}
    if trial_ends and stamp < trial_ends:
        return {"plan": account["plan"], "status": "trial", "expiresAt": iso(trial_ends),
                "trialEndsAt": account.get("trial_ends_at"),
                "subscriptionEndsAt": account.get("subscription_ends_at")}
    return {"plan": "free", "status": "expired", "expiresAt": None,
            "trialEndsAt": account.get("trial_ends_at"),
            "subscriptionEndsAt": account.get("subscription_ends_at")}


def public_account(account: dict, now: datetime | None = None) -> dict:
    rights = entitlements(account, now)
    return {
        "id": account["id"],
        "login": account["login"],
        "name": account["name"],
        "hotel": account.get("hotel"),
        "plan": rights["plan"],
        "status": rights["status"],
        "expiresAt": rights["expiresAt"],
        "trialEndsAt": rights["trialEndsAt"],
        "subscriptionEndsAt": rights["subscriptionEndsAt"],
        "createdAt": account["created_at"],
    }


# --- login throttling ---------------------------------------------------------
# One process, in-memory: enough to stop password guessing against a demo deployment, not a
# substitute for a real rate limiter (recorded in the docs as a known limit).
_failures: dict[str, list[float]] = {}
_failures_lock = threading.Lock()


def _failure_key(remote: str | None, login: str) -> str:
    return f"{remote or '-'}|{login.lower()}"


def note_login_failure(remote: str | None, login: str, now: datetime | None = None) -> None:
    stamp = (now or now_utc()).timestamp()
    with _failures_lock:
        attempts = [value for value in _failures.get(_failure_key(remote, login), [])
                    if stamp - value < LOGIN_WINDOW_SECONDS]
        attempts.append(stamp)
        _failures[_failure_key(remote, login)] = attempts


def login_locked(remote: str | None, login: str, now: datetime | None = None) -> bool:
    stamp = (now or now_utc()).timestamp()
    with _failures_lock:
        attempts = [value for value in _failures.get(_failure_key(remote, login), [])
                    if stamp - value < LOGIN_WINDOW_SECONDS]
        _failures[_failure_key(remote, login)] = attempts
        return len(attempts) >= MAX_LOGIN_FAILURES


def clear_login_failures(remote: str | None, login: str) -> None:
    with _failures_lock:
        _failures.pop(_failure_key(remote, login), None)


# --- invites ------------------------------------------------------------------
def _new_code() -> str:
    groups = ["".join(secrets.choice(INVITE_ALPHABET) for _ in range(4)) for _ in range(2)]
    return "MND-" + "-".join(groups)


def create_invite(con, *, plan: str, trial_days: int, max_uses: int, note: str | None,
                  created_by: str, expires_in_days: int | None) -> dict:
    if plan not in PLAN_PRICES:
        raise ValueError("unknown plan")
    if not 1 <= trial_days <= 365:
        raise ValueError("trial days must be between 1 and 365")
    if not 1 <= max_uses <= 100:
        raise ValueError("max uses must be between 1 and 100")
    stamp = now_utc()
    expires_at = iso(stamp + timedelta(days=expires_in_days)) if expires_in_days else None
    for _ in range(20):
        code = _new_code()
        try:
            con.execute(
                "INSERT INTO invite_codes(code, plan, trial_days, max_uses, note, created_by, "
                "created_at, expires_at) VALUES(?,?,?,?,?,?,?,?)",
                (code, plan, trial_days, max_uses, note, created_by, iso(stamp), expires_at),
            )
        except sqlite3.IntegrityError:
            continue
        return {"code": code, "plan": plan, "trialDays": trial_days, "maxUses": max_uses,
                "usedCount": 0, "note": note, "createdBy": created_by,
                "createdAt": iso(stamp), "expiresAt": expires_at, "status": "open"}
    raise RuntimeError("could not allocate an invite code")


def _invite_status(invite: dict, now: datetime) -> str:
    if invite["used_count"] >= invite["max_uses"]:
        return "used"
    expires = parse(invite["expires_at"])
    if expires and now >= expires:
        return "expired"
    return "open"


def list_invites(con, now: datetime | None = None) -> list[dict]:
    stamp = now or now_utc()
    rows = con.execute("SELECT * FROM invite_codes ORDER BY created_at DESC").fetchall()
    return [{**row, "status": _invite_status(row, stamp)} for row in rows]


def use_invite(con, code: str, now: datetime | None = None) -> dict:
    """Consume one use of an invite inside the caller's transaction."""
    stamp = now or now_utc()
    row = con.execute("SELECT * FROM invite_codes WHERE code=?", (code.strip().upper(),)).fetchone()
    if row is None:
        raise LookupError("邀请码不存在")
    invite = dict(row)
    if invite["used_count"] >= invite["max_uses"]:
        raise LookupError("邀请码已用完")
    expires = parse(invite["expires_at"])
    if expires and stamp >= expires:
        raise LookupError("邀请码已过期")
    con.execute("UPDATE invite_codes SET used_count=used_count+1 WHERE code=?", (invite["code"],))
    return invite


# --- accounts -----------------------------------------------------------------
def register(con, *, invite_code: str, login: str, password: str, name: str,
             hotel: str | None = None, now: datetime | None = None,
             remote: str | None = None) -> tuple[dict, str]:
    stamp = now or now_utc()
    login = login.strip()
    name = name.strip()
    if not LOGIN_RE.match(login):
        raise ValueError("登录名需 3–32 位字母、数字或 . _ -")
    if len(password) < 8:
        raise ValueError("密码至少 8 位")
    if not name:
        raise ValueError("请填写称呼")
    invite = use_invite(con, invite_code, stamp)
    trial_ends = stamp + timedelta(days=int(invite["trial_days"]))
    account_id = "cus_" + secrets.token_hex(8)
    try:
        con.execute(
            "INSERT INTO customer_accounts(id, login, name, hotel, password_hash, plan, "
            "trial_ends_at, subscription_ends_at, invite_code, suspended, created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,0,?)",
            (account_id, login, name, (hotel or "").strip() or None,
             hash_password(password), invite["plan"], iso(trial_ends), None,
             invite["code"], iso(stamp)),
        )
    except sqlite3.IntegrityError as exc:
        raise ValueError("这个登录名已被使用") from exc
    account = dict(con.execute("SELECT * FROM customer_accounts WHERE id=?", (account_id,)).fetchone())
    return account, create_session(con, account_id)


def authenticate(con, *, login: str, password: str, remote: str | None = None,
                 now: datetime | None = None) -> dict:
    stamp = now or now_utc()
    if login_locked(remote, login, stamp):
        raise PermissionError("尝试次数过多，请 15 分钟后再试")
    row = con.execute("SELECT * FROM customer_accounts WHERE login=?", (login.strip(),)).fetchone()
    if row is None or not verify_password(password, row["password_hash"]):
        note_login_failure(remote, login, stamp)
        raise PermissionError("登录名或密码不正确")
    clear_login_failures(remote, login)
    con.execute("UPDATE customer_accounts SET last_login_at=? WHERE id=?",
                (iso(stamp), row["id"]))
    return dict(row)


# --- orders (offline payment) -------------------------------------------------
def request_order(con, *, account: dict, plan: str, months: int, note: str | None,
                  now: datetime | None = None) -> dict:
    stamp = now or now_utc()
    if plan not in PLAN_PRICES:
        raise ValueError("未知套餐")
    if not 1 <= months <= 36:
        raise ValueError("购买月数需在 1–36 之间")
    order_id = "ord_" + secrets.token_hex(8)
    amount = PLAN_PRICES[plan] * months
    con.execute(
        "INSERT INTO customer_orders(id, account_id, plan, months, amount_cny, note, status, "
        "created_at) VALUES(?,?,?,?,?,?,'pending',?)",
        (order_id, account["id"], plan, months, amount, note, iso(stamp)),
    )
    return dict(con.execute("SELECT * FROM customer_orders WHERE id=?", (order_id,)).fetchone())


def list_orders(con, *, account_id: str | None = None, status: str | None = None) -> list[dict]:
    clauses, params = [], []
    if account_id:
        clauses.append("account_id=?")
        params.append(account_id)
    if status:
        clauses.append("status=?")
        params.append(status)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = con.execute(
        "SELECT o.*, a.login AS account_login, a.name AS account_name, a.hotel AS account_hotel "
        f"FROM customer_orders o JOIN customer_accounts a ON a.id = o.account_id{where} "
        "ORDER BY o.created_at DESC",
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def confirm_order(con, *, order_id: str, confirmed_by: str,
                  now: datetime | None = None) -> dict:
    stamp = now or now_utc()
    row = con.execute("SELECT * FROM customer_orders WHERE id=?", (order_id,)).fetchone()
    if row is None:
        raise LookupError("订单不存在")
    order = dict(row)
    if order["status"] != "pending":
        raise ValueError(f"订单状态是 {order['status']}，不能确认")
    account = dict(con.execute("SELECT * FROM customer_accounts WHERE id=?",
                               (order["account_id"],)).fetchone())
    current_end = parse(account.get("subscription_ends_at"))
    start = current_end if current_end and current_end > stamp else stamp
    new_end = add_months(start, int(order["months"]))
    con.execute(
        "UPDATE customer_accounts SET plan=?, subscription_ends_at=?, suspended=0 WHERE id=?",
        (order["plan"], iso(new_end), account["id"]),
    )
    con.execute(
        "UPDATE customer_orders SET status='confirmed', confirmed_at=?, confirmed_by=? WHERE id=?",
        (iso(stamp), confirmed_by, order_id),
    )
    return {"order": dict(con.execute("SELECT * FROM customer_orders WHERE id=?",
                                     (order_id,)).fetchone()),
            "account": dict(con.execute("SELECT * FROM customer_accounts WHERE id=?",
                                        (account["id"],)).fetchone())}


def cancel_order(con, *, order_id: str, now: datetime | None = None) -> dict:
    stamp = now or now_utc()
    row = con.execute("SELECT * FROM customer_orders WHERE id=?", (order_id,)).fetchone()
    if row is None:
        raise LookupError("订单不存在")
    if row["status"] != "pending":
        raise ValueError(f"订单状态是 {row['status']}，不能取消")
    con.execute("UPDATE customer_orders SET status='cancelled', confirmed_at=? WHERE id=?",
                (iso(stamp), order_id))
    return dict(con.execute("SELECT * FROM customer_orders WHERE id=?", (order_id,)).fetchone())


def list_accounts(con, now: datetime | None = None) -> list[dict]:
    stamp = now or now_utc()
    rows = con.execute(
        "SELECT a.*, (SELECT count(*) FROM customer_orders o WHERE o.account_id=a.id "
        "AND o.status='pending') AS pending_orders FROM customer_accounts a "
        "ORDER BY a.created_at DESC"
    ).fetchall()
    accounts = []
    for row in rows:
        record = dict(row)
        rights = entitlements(record, stamp)
        accounts.append({**public_account(record, stamp),
                         "pendingOrders": record["pending_orders"],
                         "lastLoginAt": record["last_login_at"]})
        accounts[-1]["plan"] = rights["plan"]
    return accounts
