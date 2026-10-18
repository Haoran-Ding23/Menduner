"""Write access control.

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

A script that cannot log in through a browser (a repair run, a curl in a runbook) sends
``Authorization: Bearer $MENDUNER_WRITE_TOKEN`` instead; the token is optional, server-side only,
and never reaches the bundle.
"""
from __future__ import annotations

import hmac
import os

from fastapi import HTTPException, Request

LOGIN_HEADER = "X-Menduner-Login"
TOKEN_ENV = "MENDUNER_WRITE_TOKEN"
_RESTRICTED = (
    "写操作需要身份：请通过站点口令登录后操作（nginx 会把登录名转发为 {login}），"
    "或用 Bearer 令牌（{token}）调用。读接口不受影响。"
).format(login=LOGIN_HEADER, token=TOKEN_ENV)


def principal(request: Request) -> str:
    """The authenticated identity behind a write, or 401.

    Used directly as a FastAPI dependency on every mutating route. The recorded ``reviewer``
    name is still the human's own attribution (people sign their own name, not a shared login);
    this is what decides whether the write happens at all.
    """
    login = (request.headers.get(LOGIN_HEADER) or "").strip()
    if login:
        return login
    configured = (os.environ.get(TOKEN_ENV) or "").strip()
    authorization = request.headers.get("Authorization") or ""
    if configured and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
        if supplied and hmac.compare_digest(supplied, configured):
            return "token"
    raise HTTPException(status_code=401, detail=_RESTRICTED)
