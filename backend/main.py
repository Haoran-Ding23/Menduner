from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from backend import bulk_review
from backend import client_errors
from backend.amap import amap_place_url
from backend import venues as venue_store
from backend.database import connect, database_path, initialize, snapshot
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


def create_app(db_path: Path | None = None):
    path = db_path or database_path()

    @asynccontextmanager
    async def lifespan(app):
        initialize(path)
        yield

    app = FastAPI(title='Menduner Event Intelligence API', version='1.6.3', lifespan=lifespan,
                  description='Local SQLite prototype. Field claims are verified only from official sources with deterministic extraction; everything else is queued for human review. No pricing or revenue prediction.')

    @app.get('/dataset')
    def dataset():
        """One read transaction keeps all six frontend pages on a consistent revision."""
        return snapshot(path)

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

    @app.get('/review')
    def review_queue():
        """Every recorded human decision, newest first."""
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
    def crawl_runs(limit: int = 100):
        """The per-source crawl log: when each source ran, its status, how many events it
        produced and why it failed."""
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
    def list_client_errors(limit: int = 50):
        """Recent browser errors, newest first, so a phone failure can be read from a desktop."""
        with connect(path) as con:
            return client_errors.recent(con, limit=limit)

    @app.post('/review/event')
    def check_whole_event(body: CheckEventRequest):
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
        return result

    @app.get('/review/{event_id}')
    def event_review(event_id: str):
        with connect(path) as con:
            return list(review.decisions_for(con, event_id).values())

    @app.post('/review')
    def record_review(body: ReviewRequest):
        """Record a human decision. A correction must carry a replacement value."""
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
        with connect(path) as con:
            recorded = review.record(
                con,
                event_id=body.event_id,
                field=body.field,
                decision=body.decision,
                reviewed_value=body.value,
                corrected_value=body.corrected_value,
                reviewer=body.reviewer,
                note=body.note,
                decided_at=datetime.now(timezone.utc).isoformat(),
            )
        # A decision only reaches the frontend once the event's evidence rows are rebuilt,
        # because the served rows are stored, not computed. Without this the reviewer would
        # approve a field and see no change until the next crawl.
        reproject_event(path, body.event_id)
        return recorded

    @app.delete('/review/{event_id}/{field}')
    def clear_review(event_id: str, field: str):
        """Withdraw a decision, returning the field to the unreviewed queue."""
        with connect(path) as con:
            review.ensure_schema(con)
            cur = con.execute(
                "DELETE FROM review_decisions WHERE event_id=? AND field=?",
                (event_id, field),
            )
        reproject_event(path, event_id)
        return {'removed': cur.rowcount}

    @app.get('/venues/duplicates')
    def venue_duplicates():
        """Pairs that LOOK like one place. Nothing merges until a human says so."""
        return venue_store.duplicates(path)

    @app.get('/venues/coordinates/needed')
    def coordinates_needed():
        """Venues an event references but which carry no usable coordinate yet."""
        return venue_store.coordinate_targets(path)

    @app.get('/venues/edits')
    def edits():
        return venue_store.venue_edits(path)

    @app.post('/venues/merge')
    def merge_venues(body: MergeRequest):
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
        return result

    @app.post('/venues/coordinates')
    def set_venue_coordinates(body: CoordinatesRequest):
        """Record a human-checked coordinate. Bounds and provenance are enforced."""
        try:
            lng, lat = body.parsed()
            # A reviewer pasting AMap coordinates should not also have to prove where they came
            # from: the AMap place URL is resolved from the coordinate itself. AMap's own web
            # UI has no stable per-place URL, so asking for one was pure friction.
            source_url = (body.source_url or '').strip() or amap_place_url(lng, lat)
            return venue_store.set_coordinates(
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

    return app

app = create_app()
