import hashlib
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field
from backend import accounts
from backend import auth
from backend import bulk_review
from backend import client_errors
from backend.amap import amap_place_url
from backend import venues as venue_store
from backend.database import connect, database_path, initialize, snapshot, snapshot_bytes
from crawler import crawl_log, review


class ReviewRequest(BaseModel):
    """One human decision about one field of one event."""

    event_id: str = Field(min_length=1)
    field: str = Field(min_length=1)
    decision: str
    value: object | None = None
    corrected_value: object | None = None
    reviewer: str = Field(min_length=1, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class MergeRequest(BaseModel):
    """A human decision that two venue rows are the same place."""

    alias_id: str = Field(min_length=1)
    canonical_id: str = Field(min_length=1)
    reviewer: str = Field(min_length=1, max_length=80)
    reason: str = Field(min_length=1, max_length=500)
    evidence_url: str | None = None
    revert: bool = False


class ClientErrorRequest(BaseModel):
    """A browser-side error report. Every field is optional: a reporter that has already
    crashed should not be rejected for being incomplete."""

    message: str | None = Field(default=None, max_length=500)
    source: str | None = Field(default=None, max_length=300)
    stack: str | None = Field(default=None, max_length=4000)
    page: str | None = Field(default=None, max_length=300)
    userAgent: str | None = Field(default=None, max_length=400)
    viewport: str | None = Field(default=None, max_length=40)
    extra: dict | None = None


class CoordinatesRequest(BaseModel):
    """A human-checked coordinate for a venue, with the source that fixes it.

    The coordinate arrives as the single string AMap's 坐标拾取 produces — "120.7,31.3" —
    because splitting it into two fields made the reviewer do the parsing. Explicit numbers are
    still accepted so an API client is not forced to build a string.
    """

    venue_id: str = Field(min_length=1)
    coordinates: str | None = None
    lng: float | None = None
    lat: float | None = None
    source_url: str | None = None
    reviewer: str = Field(min_length=1, max_length=80)
    note: str | None = Field(default=None, max_length=500)

    def parsed(self) -> tuple[float, float]:
        """The coordinate pair, from either the pasted string or the explicit numbers."""
        if self.coordinates is not None and self.coordinates.strip():
            parts = [
                piece.strip()
                for piece in self.coordinates.replace("，", ",").replace(" ", ",").split(",")
                if piece.strip()
            ]
            if len(parts) != 2:
                raise ValueError(
                    "坐标要写成「经度,纬度」，例如 120.704315,31.322250（请从高德复制）"
                )
            try:
                lng, lat = float(parts[0]), float(parts[1])
            except ValueError as exc:
                raise ValueError("坐标里有非数字内容，请重新从高德复制") from exc
            # A swapped paste is the common mistake and is detectable: Suzhou's longitude is
            # near 120 and its latitude near 31.
            if abs(lng) < 60 and abs(lat) > 60:
                raise ValueError("经纬度写反了：经度应在 120 附近，纬度应在 31 附近")
            return lng, lat
        if self.lng is None or self.lat is None:
            raise ValueError("请填写坐标")
        return self.lng, self.lat


class CheckEventRequest(BaseModel):
    """A reviewer settling every factual field of one event in one action."""

    event_id: str = Field(min_length=1)
    reviewer: str = Field(min_length=1, max_length=80)


class RegisterRequest(BaseModel):
    """A customer self-registration; the invite code is what authorises the trial."""

    invite_code: str = Field(min_length=1, max_length=40)
    login: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=40)
    hotel: str | None = Field(default=None, max_length=80)


class LoginRequest(BaseModel):
    login: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=1, max_length=200)


class OrderRequest(BaseModel):
    """A payment request for the offline (对公转账) flow. The amount is computed server-side."""

    plan: str = Field(min_length=2, max_length=20)
    months: int = Field(ge=1, le=36)
    note: str | None = Field(default=None, max_length=200)


class InviteRequest(BaseModel):
    plan: str = Field(default="pro", min_length=2, max_length=20)
    trial_days: int = Field(default=28, ge=1, le=365)
    max_uses: int = Field(default=1, ge=1, le=100)
    expires_in_days: int | None = Field(default=30, ge=1, le=365)
    note: str | None = Field(default=None, max_length=200)


def _client_ip(request: Request) -> str | None:
    """The nginx-forwarded client address (falls back to the direct peer)."""
    return request.headers.get('x-real-ip') or (request.client.host if request.client else None)


def _is_https(request: Request) -> bool:
    """Whether the browser reached us over TLS (nginx sets X-Forwarded-Proto).

    The site serves both http://<ip> (for the current deployment) and https://<domain> (after the
    certificate exists), so the session cookie gets the Secure flag only on TLS: forcing it while
    the IP is still http would make customer logins silently stop working there.
    """
    forwarded = (request.headers.get('x-forwarded-proto') or '').split(',')[0].strip()
    return forwarded == 'https'


def _session_token(request: Request) -> str | None:
    return request.cookies.get(accounts.SESSION_COOKIE)


def _public_order(row: dict) -> dict:
    return {
        'id': row['id'],
        'plan': row['plan'],
        'months': row['months'],
        'amountCny': row['amount_cny'],
        'note': row.get('note'),
        'status': row['status'],
        'createdAt': row['created_at'],
        'confirmedAt': row.get('confirmed_at'),
    }


def _admin_order(row: dict) -> dict:
    return {
        **_public_order(row),
        'confirmedBy': row.get('confirmed_by'),
        'accountLogin': row.get('account_login'),
        'accountName': row.get('account_name'),
        'accountHotel': row.get('account_hotel'),
    }


def _account_state(con, request: Request, token: str | None = None) -> dict:
    """The customer's own view: who they are, the plan derived from their dates, their orders."""
    account = accounts.session_account(con, token or _session_token(request))
    if account is None:
        return {'authenticated': False, 'account': None, 'orders': []}
    rows = accounts.list_orders(con, account_id=account['id'])
    return {
        'authenticated': True,
        'account': accounts.public_account(account),
        'orders': [_public_order(row) for row in rows],
    }



def reproject_event(db_path: Path, event_id: str) -> None:
    """Rebuild one event's evidence rows so a just-recorded review decision takes effect.

    The served evidence rows are stored, and the pipeline writes them during a crawl. A
    review decision therefore has no visible effect until the event is rebuilt, which would
    make approving a field appear to do nothing. This reuses the pipeline's own projection
    (``refresh_event``) with the registry's trust levels, so the recomputed statuses are
    identical to what the next crawl would produce.
    """
    from crawler.pipeline import refresh_event, source_metadata
    from crawler.registry import REGISTRY_PATH, load_registry

    try:
        definitions = load_registry(REGISTRY_PATH)
    except Exception:
        definitions = []
    meta = source_metadata(
        type("Definition", (), {"source_id": d.source_id, "trust_level": d.trust_level})
        for d in definitions
    )
    with connect(db_path) as con:
        refresh_event(con, event_id, datetime.now(timezone.utc).isoformat(), meta)


def stored_claim(db_path: Path, event_id: str, field: str) -> tuple[bool, object]:
    """``(exists, value)`` of the claim a reviewer is judging, as the API serves it.

    The served value lives in ``evidence.payload`` (``snapshot`` reads that, not the value
    column), so that is what a decision has to be bound to. Binding it is the whole point of
    the review table: a decision stands for the one value the reviewer saw.
    """
    with connect(db_path) as con:
        row = con.execute(
            "SELECT value, payload FROM evidence WHERE entity_id=? AND field=?",
            (event_id, field),
        ).fetchone()
    if row is None:
        return False, None
    try:
        payload = json.loads(row["payload"]) if row["payload"] else {}
    except ValueError:
        payload = {}
    if "value" in payload:
        return True, payload["value"]
    try:
        return True, json.loads(row["value"]) if row["value"] is not None else None
    except ValueError:
        return True, row["value"]


def _etag_matches(header: str | None, etag: str) -> bool:
    """Whether an If-None-Match header covers this ETag (weak prefixes and lists allowed)."""
    if not header:
        return False
    for candidate in header.split(','):
        candidate = candidate.strip()
        if candidate.startswith('W/'):
            candidate = candidate[2:]
        if candidate == etag or candidate == '*':
            return True
    return False


def create_app(db_path: Path | None = None):
    path = db_path or database_path()

    @asynccontextmanager
    async def lifespan(app):
        initialize(path)
        yield

    app = FastAPI(title='Menduner Event Intelligence API', version='1.6.3', lifespan=lifespan,
                  description='Local SQLite prototype. Field claims are verified only from official sources with deterministic extraction; everything else is queued for human review. No pricing or revenue prediction.')

    @app.get('/dataset')
    def dataset(request: Request):
        """One read transaction keeps all six frontend pages on a consistent revision.

        The body is ~5 MB, so it is served with a strong ETag: a returning browser revalidates
        and gets a 304 with no body instead of re-downloading the whole snapshot. That is not a
        micro-optimisation — the payload is 87% evidence rows, the link is often a phone, and a
        10 s client timeout used to abort a first load on a slow one.
        """
        body = snapshot_bytes(path)
        etag = '"' + hashlib.sha256(body).hexdigest()[:32] + '"'
        headers = {'ETag': etag, 'Cache-Control': 'no-cache'}
        if _etag_matches(request.headers.get('if-none-match'), etag):
            return Response(status_code=304, headers=headers)
        return Response(content=body, media_type='application/json', headers=headers)

    @app.get('/events')
    def events():
        return snapshot(path)['events']

    @app.get('/events/{event_id}')
    def event(event_id: str):
        row = next((e for e in snapshot(path)['events'] if e['id'] == event_id), None)
        if row is None:
            raise HTTPException(status_code=404, detail='Event not found')
        return row

    @app.get('/venues')
    def venues():
        return snapshot(path)['venues']

    @app.get('/evidence')
    def evidence(event_id: str | None = None):
        rows = snapshot(path)['evidence']
        return rows if event_id is None else [e for e in rows if e['event_id'] == event_id]

    @app.get('/hotels')
    def hotels():
        return snapshot(path)['hotels']

    @app.get('/districts')
    def districts():
        return snapshot(path)['districts']

    @app.get('/places')
    def places():
        """Restaurants and public transport sampled around the venues that hold events."""
        return snapshot(path)['places']

    @app.get('/status')
    def status():
        return snapshot(path)['status']

    @app.get('/auth/me')
    def whoami(request: Request):
        """Who this browser is, so the UI can show the role or a read-only notice.

        Never raises: an anonymous visitor is the normal case (the public pages read the dataset
        without a login), and this endpoint must not become a second login wall.
        """
        return auth.identity(request)

    # --- customer accounts: the product side (session cookie, no HTTP Basic) -----------------
    # nginx must not challenge these with Basic (customers do not have operator credentials);
    # they authenticate themselves with the session cookie and the backend rate-limits logins.
    @app.post('/account/register')
    def customer_register(body: RegisterRequest, request: Request, response: Response):
        """Redeem an invite code, create the account on a trial, and sign in."""
        with connect(path) as con:
            try:
                account, token = accounts.register(
                    con,
                    invite_code=body.invite_code,
                    login=body.login,
                    password=body.password,
                    name=body.name,
                    hotel=body.hotel,
                    remote=_client_ip(request),
                )
            except LookupError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except ValueError as exc:
                detail = str(exc)
                status = 409 if '已被使用' in detail else 400
                raise HTTPException(status_code=status, detail=detail) from exc
            response.set_cookie(
                accounts.SESSION_COOKIE, token, httponly=True, samesite='lax',
                secure=_is_https(request),
                max_age=accounts.SESSION_DAYS * 86400, path='/',
            )
            return _account_state(con, request, token)

    @app.post('/account/login')
    def customer_login(body: LoginRequest, request: Request, response: Response):
        with connect(path) as con:
            try:
                account = accounts.authenticate(
                    con, login=body.login, password=body.password, remote=_client_ip(request)
                )
            except PermissionError as exc:
                raise HTTPException(status_code=401, detail=str(exc)) from exc
            token = accounts.create_session(con, account['id'])
            response.set_cookie(
                accounts.SESSION_COOKIE, token, httponly=True, samesite='lax',
                secure=_is_https(request),
                max_age=accounts.SESSION_DAYS * 86400, path='/',
            )
            return _account_state(con, request, token)

    @app.post('/account/logout')
    def customer_logout(request: Request, response: Response):
        with connect(path) as con:
            accounts.delete_session(con, _session_token(request))
        response.delete_cookie(accounts.SESSION_COOKIE, path='/')
        return {'authenticated': False, 'account': None, 'orders': []}

    @app.get('/account')
    def customer_account(request: Request):
        """Who the customer is and which plan their dates currently grant (never raises)."""
        with connect(path) as con:
            return _account_state(con, request)

    @app.post('/account/orders')
    def customer_order(body: OrderRequest, request: Request):
        """File an offline payment request. Nothing is unlocked until an operator confirms it."""
        with connect(path) as con:
            account = accounts.session_account(con, _session_token(request))
            if account is None:
                raise HTTPException(status_code=401, detail='请先登录')
            try:
                order = accounts.request_order(
                    con, account=account, plan=body.plan, months=body.months, note=body.note
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            return {'order': _public_order(order), 'account': accounts.public_account(account)}

    # --- operator side: invites, customers and the offline payment queue (HTTP Basic, admin) --
    @app.post('/admin/invites')
    def create_invite(body: InviteRequest,
                      principal: str = Depends(auth.require_role(auth.ROLE_ADMIN))):
        with connect(path) as con:
            try:
                invite = accounts.create_invite(
                    con, plan=body.plan, trial_days=body.trial_days, max_uses=body.max_uses,
                    note=body.note, created_by=principal, expires_in_days=body.expires_in_days,
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            return {'invite': invite, 'invites': accounts.list_invites(con)}

    @app.get('/admin/invites')
    def admin_invites(principal: str = Depends(auth.require_role(auth.ROLE_ADMIN))):
        with connect(path) as con:
            return {'invites': accounts.list_invites(con)}

    @app.get('/admin/accounts')
    def admin_accounts(principal: str = Depends(auth.require_role(auth.ROLE_ADMIN))):
        with connect(path) as con:
            return {'accounts': accounts.list_accounts(con)}

    @app.get('/admin/orders')
    def admin_orders(status: str | None = None,
                     principal: str = Depends(auth.require_role(auth.ROLE_ADMIN))):
        with connect(path) as con:
            rows = accounts.list_orders(con, status=status)
            return {'orders': [_admin_order(row) for row in rows]}

    @app.post('/admin/orders/{order_id}/confirm')
    def admin_confirm_order(order_id: str,
                            principal: str = Depends(auth.require_role(auth.ROLE_ADMIN))):
        """Money arrived offline: extend the subscription by calendar months and open the plan."""
        with connect(path) as con:
            try:
                result = accounts.confirm_order(con, order_id=order_id, confirmed_by=principal)
            except LookupError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            return {'order': _admin_order(result['order']),
                    'account': accounts.public_account(result['account'])}

    @app.post('/admin/orders/{order_id}/cancel')
    def admin_cancel_order(order_id: str,
                           principal: str = Depends(auth.require_role(auth.ROLE_ADMIN))):
        with connect(path) as con:
            try:
                order = accounts.cancel_order(con, order_id=order_id)
            except LookupError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            return {'order': _public_order(order)}

    @app.get('/review')
    def review_queue(principal: str = Depends(auth.require_role(auth.ROLE_REVIEWER))):
        """Every recorded human decision, newest first. Internal: reviewer role required."""
        with connect(path) as con:
            review.ensure_schema(con)
            return [
                dict(r)
                for r in con.execute(
                    "SELECT * FROM review_decisions ORDER BY decided_at DESC"
                )
            ]

    @app.get('/crawl/health')
    def crawl_health():
        """Per-source last run, consecutive failures and any open alert.

        A source that stopped working used to be invisible: the crawl report said "Failed" and
        nothing recorded it, so "broken for one run" and "broken for three weeks" looked the
        same. This is what the frontend reads to tell them apart.
        """
        with connect(path) as con:
            return {
                'sources': crawl_log.source_health(con),
                'alerts': crawl_log.open_alerts(con),
            }

    @app.get('/crawl/runs')
    def crawl_runs(limit: int = 100,
                   principal: str = Depends(auth.require_role(auth.ROLE_REVIEWER))):
        """The per-source crawl log: when each source ran, its status, how many events it
        produced and why it failed. Operational detail, not a customer-facing trust signal."""
        with connect(path) as con:
            return crawl_log.recent_runs(con, limit=max(1, min(limit, 1000)))

    @app.post('/client-error')
    def report_client_error(body: ClientErrorRequest):
        """Record a browser-side error.

        Deliberately unauthenticated and never failing: this is the last resort for a client
        that has already broken, and a 4xx here would lose the only evidence of why. Anything
        malformed is clipped rather than rejected.
        """
        with connect(path) as con:
            client_errors.record(
                con,
                report=body.model_dump(),
                occurred_at=datetime.now(timezone.utc).isoformat(),
            )
        return {'ok': True}

    @app.get('/client-errors')
    def list_client_errors(limit: int = 50,
                          principal: str = Depends(auth.require_role(auth.ROLE_REVIEWER))):
        """Recent browser errors, newest first, so a phone failure can be read from a desktop.

        Internal: the log names pages and devices of real visitors. Ingestion above stays open
        because a crashing client cannot authenticate; reading it does not have that excuse.
        """
        with connect(path) as con:
            return client_errors.recent(con, limit=limit)

    @app.post('/review/event')
    def check_whole_event(body: CheckEventRequest, principal: str = Depends(auth.require_role(auth.ROLE_REVIEWER))):
        """Settle every factual field of one event, and report what remains."""
        try:
            result = bulk_review.check_event(path, body.event_id, body.reviewer)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        reproject_event(path, body.event_id)
        after = snapshot(path)
        row = next(
            (
                e
                for e in after['evidence']
                if e['entityId'] == body.event_id and e['field'] == 'venueId'
            ),
            None,
        )
        result['venue_reference_status'] = row['status'] if row else None
        result['authenticated_as'] = principal
        return result

    @app.get('/review/{event_id}')
    def event_review(event_id: str,
                     principal: str = Depends(auth.require_role(auth.ROLE_REVIEWER))):
        """One event's recorded decisions. Internal: it is the audit trail, not public data."""
        with connect(path) as con:
            return list(review.decisions_for(con, event_id).values())

    @app.post('/review')
    def record_review(body: ReviewRequest, principal: str = Depends(auth.require_role(auth.ROLE_REVIEWER))):
        """Record a human decision bound to the claim that was on screen.

        A decision records the value the reviewer actually saw. If the request names a value
        that is no longer the stored claim, the page was stale and the decision would bind to
        something the reviewer never saw, so it is refused with 409 and the reviewer reloads.
        Omitting the value is not an error: the binding is read from the stored claim. It used
        to mean "no binding at all", which let one value-less approval keep verifying every
        later value that appeared — a review that silently extends past what a human approved.
        """
        if body.decision not in review.DECISIONS:
            raise HTTPException(
                status_code=400,
                detail=f"decision must be one of {list(review.DECISIONS)}",
            )
        if body.decision == review.CORRECT and body.corrected_value in (None, ""):
            raise HTTPException(
                status_code=400, detail="A correction must carry a replacement value"
            )
        if body.event_id not in {e['id'] for e in snapshot(path)['events']}:
            raise HTTPException(status_code=404, detail='Event not found')
        exists, current = stored_claim(path, body.event_id, body.field)
        if not exists:
            raise HTTPException(
                status_code=404,
                detail=f"活动 {body.event_id} 没有字段 {body.field} 的证据记录，无法审核",
            )
        if body.value is not None and review.normalized(body.value) != review.normalized(current):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"字段 {body.field} 的证据已变化（当前值：{json.dumps(current, ensure_ascii=False)}）。"
                    "请刷新后重新审核。"
                ),
            )
        with connect(path) as con:
            recorded = review.record(
                con,
                event_id=body.event_id,
                field=body.field,
                decision=body.decision,
                reviewed_value=current,
                corrected_value=body.corrected_value,
                reviewer=body.reviewer,
                note=body.note,
                decided_at=datetime.now(timezone.utc).isoformat(),
            )
        # A decision only reaches the frontend once the event's evidence rows are rebuilt,
        # because the served rows are stored, not computed. Without this the reviewer would
        # approve a field and see no change until the next crawl.
        reproject_event(path, body.event_id)
        recorded['authenticated_as'] = principal
        return recorded

    @app.delete('/review/{event_id}/{field}')
    def clear_review(event_id: str, field: str,
                     principal: str = Depends(auth.require_role(auth.ROLE_REVIEWER))):
        """Withdraw a decision, returning the field to the unreviewed queue."""
        with connect(path) as con:
            review.ensure_schema(con)
            cur = con.execute(
                "DELETE FROM review_decisions WHERE event_id=? AND field=?",
                (event_id, field),
            )
        reproject_event(path, event_id)
        return {'removed': cur.rowcount, 'authenticated_as': principal}

    @app.get('/venues/duplicates')
    def venue_duplicates(principal: str = Depends(auth.require_role(auth.ROLE_REVIEWER))):
        """Pairs that LOOK like one place. Nothing merges until a human says so.

        Internal: the maintenance queue is operational work, not a trust signal customers read.
        """
        return venue_store.duplicates(path)

    @app.get('/venues/coordinates/needed')
    def coordinates_needed(principal: str = Depends(auth.require_role(auth.ROLE_REVIEWER))):
        """Venues an event references but which carry no usable coordinate yet."""
        return venue_store.coordinate_targets(path)

    @app.get('/venues/edits')
    def edits(principal: str = Depends(auth.require_role(auth.ROLE_REVIEWER))):
        return venue_store.venue_edits(path)

    @app.post('/venues/merge')
    def merge_venues(body: MergeRequest, principal: str = Depends(auth.require_role(auth.ROLE_REVIEWER))):
        """Collapse two venue rows, recording the reviewer and the reason."""
        try:
            result = venue_store.merge(
                path,
                alias_id=body.alias_id,
                canonical_id=body.canonical_id,
                reviewer=body.reviewer,
                reason=body.reason,
                evidence_url=body.evidence_url,
                revert=body.revert,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        result['authenticated_as'] = principal
        return result

    @app.post('/venues/coordinates')
    def set_venue_coordinates(body: CoordinatesRequest,
                              principal: str = Depends(auth.require_role(auth.ROLE_REVIEWER))):
        """Record a human-checked coordinate. Bounds and provenance are enforced."""
        try:
            lng, lat = body.parsed()
            # A reviewer pasting AMap coordinates should not also have to prove where they came
            # from: the AMap place URL is resolved from the coordinate itself. AMap's own web
            # UI has no stable per-place URL, so asking for one was pure friction.
            source_url = (body.source_url or '').strip() or amap_place_url(lng, lat)
            result = venue_store.set_coordinates(
                path,
                venue_id=body.venue_id,
                lng=lng,
                lat=lat,
                source_url=source_url,
                reviewer=body.reviewer,
                note=body.note,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        result['authenticated_as'] = principal
        return result

    return app

app = create_app()
