"""Write access control: who is writing, and which role they hold.

Reads stay public: every page must open for anyone with the link, and nothing about reading the
dataset changes the data. Writes do not: a review decision, a venue merge or a coordinate is the
expensive, hard-to-reverse human input this project is built around, and an open write endpoint
lets an anonymous visitor rewrite the dataset or un-verify a claim.

Two lines, because one of them was missing:

  * nginx authenticates the API with HTTP Basic (``deploy/DEPLOY.md`` section 11) and forwards
    the authenticated user as ``X-Menduner-Login``. nginx replaces any client-supplied value with
    ``$remote_user``, so the header cannot be forged through the public port.
  * this module enforces it. A write with no login is refused with 401 instead of being applied.
    That is the fail-closed half: if a deployment ever forgets the nginx rule, writes break
    loudly rather than silently reopening, which is exactly the state the reviewer found on
    2026-10-18 (``POST /review`` answered 200 with no credentials at all).

Roles, because a shared login cannot tell a reviewer from a customer:

  * ``admin``    manages accounts and authorisation; may do everything a reviewer may.
  * ``reviewer`` settles evidence, merges venues, records coordinates. The internal operations.
  * ``viewer``   reads everything public, writes nothing — a customer account.

The mapping lives in a JSON file (``MENDUNER_ROLES_PATH``, default ``backend/roles.json``) so the
pilot does not need a user table yet. An account with no role entry is denied: nginx may hold a
credential this file does not authorise, and the safe reading of that mismatch is "not allowed".

A script that cannot log in through a browser (a repair run, a curl in a runbook) sends
``Authorization: Bearer $MENDUNER_WRITE_TOKEN`` instead; the token is optional, server-side only,
and never reaches the bundle. It acts as an admin, because it is a server-side secret.
"""
from __future__ import annotations

import hmac
import json
import os
from pathlib import Path

from fastapi import HTTPException, Request

LOGIN_HEADER = "X-Menduner-Login"
TOKEN_ENV = "MENDUNER_WRITE_TOKEN"
ROLES_ENV = "MENDUNER_ROLES_PATH"
DEFAULT_ROLES_PATH = Path(__file__).resolve().parent / "roles.json"

ROLE_ADMIN = "admin"
ROLE_REVIEWER = "reviewer"
ROLE_VIEWER = "viewer"
ROLES = (ROLE_VIEWER, ROLE_REVIEWER, ROLE_ADMIN)

_RESTRICTED = (
    "写操作需要身份：请通过站点口令登录后操作（nginx 会把登录名转发为 {login}），"
    "或用 Bearer 令牌（{token}）调用。读接口不受影响。"
).format(login=LOGIN_HEADER, token=TOKEN_ENV)


def roles_path() -> Path:
    override = os.environ.get(ROLES_ENV)
    return Path(override) if override else DEFAULT_ROLES_PATH


def load_users(path: Path | None = None) -> dict[str, dict]:
    """The configured accounts, keyed by login. Missing file means no authorised account."""
    path = path or roles_path()
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except ValueError:
        return {}
    users = document.get("users")
    if not isinstance(users, dict):
        return {}
    return {
        login: entry
        for login, entry in users.items()
        if isinstance(entry, dict) and entry.get("role") in ROLES
    }


def role_of(login: str, path: Path | None = None) -> str | None:
    entry = load_users(path).get(login)
    return entry.get("role") if entry else None


def principal(request: Request) -> str:
    """The authenticated identity behind a write, or 401.

    The recorded ``reviewer`` name is still the human's own attribution (people sign their own
    name, not a shared login); this is what decides whether the write happens at all.
    """
    login = (request.headers.get(LOGIN_HEADER) or "").strip()
    if login:
        return login
    # 会话 Cookie 兜底：客户账号登录后，只要登录名在 roles.json 里有角色，就能执行写操作。
    # 角色仍来自服务端配置，前端无法伪造。
    try:
        from backend import accounts as _accounts
        from backend.database import connect as _connect, database_path as _database_path

        token = request.cookies.get(_accounts.SESSION_COOKIE)
        if token:
            with _connect(_database_path()) as con:
                account = _accounts.session_account(con, token)
            if account and account.get("login"):
                return str(account["login"])
    except Exception:
        pass
    configured = (os.environ.get(TOKEN_ENV) or "").strip()
    authorization = request.headers.get("Authorization") or ""
    if configured and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
        if supplied and hmac.compare_digest(supplied, configured):
            return "token"
    raise HTTPException(status_code=401, detail=_RESTRICTED)


# Higher rank includes the lower ones: an admin may review, a reviewer may not manage accounts.
_RANK = {ROLE_VIEWER: 0, ROLE_REVIEWER: 1, ROLE_ADMIN: 2}


def require_role(*allowed: str):
    """FastAPI dependency: the caller must be authenticated AND hold one of these roles.

    Returns the login (so route handlers can report ``authenticated_as``), or raises 401/403.
    Routes read as ``Depends(auth.require_role(auth.ROLE_REVIEWER))``. The check is server-side:
    hiding a button in the UI is not a permission.
    """
    if not allowed:
        raise ValueError("require_role needs at least one role")
    minimum = min(_RANK[role] for role in allowed)

    def dependency(request: Request) -> str:
        login = principal(request)
        if login == "token":
            # A server-side secret already grants the deployment's full trust.
            return "token"
        role = role_of(login)
        if role is None:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"账号 {login} 没有配置角色（{ROLES_ENV}），写操作被拒绝。"
                    "请联系管理员在角色配置中添加该账号。"
                ),
            )
        if _RANK[role] < minimum:
            raise HTTPException(
                status_code=403,
                detail=f"账号 {login} 的角色是 {role}，无权执行该操作（需要 {allowed[0]} 及以上）。",
            )
        return login

    return dependency


def identity(request: Request) -> dict:
    """Best-effort identity for a read-only endpoint: never raises."""
    try:
        login = principal(request)
    except HTTPException:
        return {"authenticated": False, "login": None, "role": None}
    if login == "token":
        return {"authenticated": True, "login": "token", "role": ROLE_ADMIN}
    entry = load_users().get(login) or {}
    return {
        "authenticated": True,
        "login": login,
        "role": entry.get("role"),
        "name": entry.get("name"),
    }
