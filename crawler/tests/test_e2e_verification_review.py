"""End-to-end: real pipeline data + the auto-verification rule + human review.

These tests close the V1.6.3 loop on REAL crawler records rather than the demo fixtures,
because the demo path always carried ``demo: true``, which short-circuits every verification
rule and therefore never exercised the rule at all.

Pinned here:
  1. a claim from an official source with deterministic extraction reaches the frontend as
     ``Verified``, with its origin recorded so the UI can say who decided and why;
  2. an aggregator claim about the SAME event does NOT get verified, however cleanly it
     parses, and the record says WHY it is pending;
  3. a human decision survives the next crawl (which deletes and rebuilds field evidence)
     and changes the status the API serves;
  4. a human decision lapses when the underlying value changes, so a reviewer is never
     recorded as having approved a value they never saw.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.database import snapshot
from backend.main import create_app
from crawler import review, verification
from crawler.pipeline import run_pipeline
from crawler.schema import CollectedItem

OFFICIAL_URL = "https://wglj.suzhou.gov.cn/szwhgdhlyj/hdxx/202610/test.shtml"
AGGREGATOR_URL = "https://shanghaiconcerts.com/concerts/test-festival"

# Write endpoints require an authenticated caller; nginx forwards its basic-auth login as this
# header in production, and the tests send the same one.
WRITER = {"X-Menduner-Login": "test-reviewer"}


def article(venue: str = "苏州测试展览馆", name: str = "2026苏州测试文化节") -> str:
    """The selector shape the wglj.suzhou.gov.cn extractor requires: title = .con_details h2,
    body = .con_details .text, and the FIRST paragraph must begin with an explicit leading
    event date (optionally year-prefixed)."""
    return (
        "<html><body><div class='con_details'>"
        f"<h2>{name}启幕</h2>"
        "<div class='text'>"
        f"<p>2026年10月11日，{name}在{venue}启幕，为期三天。</p>"
        "<p>本届文化节由测试主办单位主办，面向公众开放。</p>"
        "</div></div></body></html>"
    )


def record(content: str, url: str, key: str, source_name: str, extractor: str):
    return CollectedItem(
        item_key=key,
        original_url=url,
        source_name=source_name,
        crawl_time=datetime.now(timezone.utc),
        raw_content=content,
        mock=False,
        extractor=extractor,
        is_event=True,
    )


class OfficialSource:
    """An OFFICIAL_GOVERNMENT source using a deterministic extractor."""

    mock = False
    source_id = "government-suzhou-culture-tourism"
    source_name = "Suzhou Culture and Tourism Bureau"
    kind = "government"
    source_url = "https://wglj.suzhou.gov.cn/szwhgdhlyj/hdxx/list.shtml"
    extractor = "official_article_v16"
    trust_level = "OFFICIAL_GOVERNMENT"

    def __init__(self, client=None, max_items=3, name: str = "2026苏州测试文化节",
                 venue: str = "苏州测试展览馆"):
        self.name = name
        self.venue = venue
        self.errors = []
        self.warnings = []
        self.pages_collected = 0
        self.request_attempts = 0

    def collect(self):
        return [
            record(
                article(self.venue, self.name),
                OFFICIAL_URL,
                "official-1",
                self.source_name,
                self.extractor,
            )
        ]


class AggregatorSource:
    """A COMMERCIAL_PLATFORM source publishing the SAME event."""

    mock = False
    source_id = "platform-shanghai-concerts"
    source_name = "上海乐历（苏州公开演出页面）"
    kind = "event_platform"
    source_url = "https://shanghaiconcerts.com/venues/suzhou-culture-arts-centre"
    extractor = "jsonld"
    trust_level = "COMMERCIAL_PLATFORM"

    def __init__(self, client=None, max_items=3, name: str = "2026苏州测试文化节"):
        self.name = name
        self.errors = []
        self.warnings = []
        self.pages_collected = 0
        self.request_attempts = 0

    def collect(self):
        # Same identity as the official article (same name, date and place) so the two
        # sources merge into ONE event. A different name would be a different fingerprint
        # and would deliberately stay a separate event, which is not what is under test.
        node = {
            "@type": "MusicEvent",
            "name": self.name,
            "startDate": "2026-10-11T19:30:00+08:00",
            "location": {
                "name": "苏州测试展览馆",
                "address": {"addressLocality": "苏州市", "streetAddress": "测试路1号"},
            },
        }
        body = (
            '<script type="application/ld+json">'
            + json.dumps(node, ensure_ascii=False)
            + "</script>"
        )
        return [
            record(
                body,
                AGGREGATOR_URL,
                "aggregator-1",
                self.source_name,
                self.extractor,
            )
        ]


@pytest.fixture
def db(tmp_path):
    return tmp_path / "e2e.sqlite3"


def event_rows(path, field: str, entity_id: str | None = None):
    return [
        r
        for r in snapshot(path)["evidence"]
        if r["field"] == field
        and r["entityId"].startswith("evt-")
        and (entity_id is None or r["entityId"] == entity_id)
    ]


def both_source_rows(path, field: str):
    """The (official, aggregator) rows for one field of the SAME merged event.

    The two sources only merge when they agree on identity, so this helper fails loudly
    rather than silently comparing rows that belong to two unrelated events.
    """
    grouped: dict[str, list[dict]] = {}
    for row in event_rows(path, field):
        grouped.setdefault(row["entityId"], []).append(row)
    for entity_id, group in grouped.items():
        official = [r for r in group if (r["sourceUrl"] or "").startswith("https://wglj.")]
        aggregator = [r for r in group if (r["sourceUrl"] or "").startswith("https://shanghai")]
        if official and aggregator:
            return entity_id, official[0], aggregator[0]
    raise AssertionError(
        "no event carries both an official and an aggregator claim for "
        f"{field}: "
        f"{[(e, [r['sourceUrl'] for r in g]) for e, g in grouped.items()]}"
    )


def crawl(db, official_name: str = "2026苏州测试文化节",
          official_venue: str = "苏州测试展览馆", aggregator: bool = True):
    adapters = [OfficialSource(name=official_name, venue=official_venue)]
    if aggregator:
        adapters.append(AggregatorSource(name=official_name))
    return run_pipeline(db, adapters)


def test_official_claim_is_verified_and_the_aggregator_copy_is_not(db):
    crawl(db)
    _, official, aggregator = both_source_rows(db, "startDate")

    # The official, deterministically extracted claim reaches the frontend as Verified.
    assert official["status"] == "Verified", official
    assert official["origin"] == "verification:auto:official_deterministic"
    assert official["decidedBy"] == "automatic"
    assert official["sourceUrl"], "a verified claim must keep its source URL"

    # The aggregator publishing the same fact does NOT become verified, however cleanly it
    # parses: the claim is theirs, not the organiser's. Its origin records WHY it is pending.
    assert aggregator["status"] != "Verified", aggregator
    assert aggregator["origin"] == "pending:aggregator_source", aggregator
    assert aggregator["decidedBy"] is None


def official_rows(path, entity_id: str) -> dict[str, dict]:
    """The official source's claim per field for one event.

    Built by explicit filter rather than "whatever a dict comprehension kept last", because
    a merged event carries a row per source per field and the official one is what must be
    inspected.
    """
    return {
        row["field"]: row
        for row in snapshot(path)["evidence"]
        if row["entityId"] == entity_id
        and (row["sourceUrl"] or "").startswith("https://wglj.")
    }


def test_rule_verifies_official_explicit_fields_and_never_derived_ones(db):
    crawl(db)
    entity_id, _, _ = both_source_rows(db, "startDate")
    official = official_rows(db, entity_id)

    # Explicit labels on an official page verify.
    for field in ("startDate", "venueName", "organizer"):
        assert official[field]["status"] == "Verified", (field, official[field])
        assert official[field]["decidedBy"] == "automatic", (field, official[field])
        assert official[field]["origin"] == "verification:auto:official_deterministic"

    # A derived value driven by a rule never verifies: `category` is a classification rule.
    for row in event_rows(db, "category", entity_id):
        assert row["status"] != "Verified", row
        assert row["decidedBy"] is None, row

    # A venue reference is a derived id and CAN verify, but only through the binding rule:
    # the venue name it points at is verified and the id was derived from that exact name.
    # It must never be attributed to the field-content rule.
    for row in event_rows(db, "venueId", entity_id):
        if row["status"] == "Verified":
            assert row["origin"] == f"verification:{verification.BINDING_ORIGIN}", row
            assert row["decidedBy"] == "automatic"
            assert row["field_name"] == "venue_id"

    # No aggregator-sourced claim may ever reach Verified.
    for row in snapshot(db)["evidence"]:
        if (row["sourceUrl"] or "").startswith("https://shanghai"):
            assert row["status"] != "Verified", row
            assert row["decidedBy"] != "automatic", row


def test_human_decision_survives_a_recrawl_and_changes_the_served_status(db):
    crawl(db)
    assert len(snapshot(db)["events"]) == 1
    event_id = snapshot(db)["events"][0]["id"]

    with TestClient(create_app(db)) as client:
        target = next(
            e
            for e in client.get(f"/evidence?event_id={event_id}").json()
            if e["field"] == "category"
        )
        assert target["status"] != "Verified"
        posted = client.post(
            "/review",
            headers=WRITER,
            json={
                "event_id": event_id,
                "field": "category",
                "decision": "Verified",
                "value": target["value"],
                "reviewer": "revenue-manager",
                "note": "confirmed as a cultural festival",
            },
        )
        assert posted.status_code == 200, posted.text

    # The next crawl deletes and rebuilds every evidence row for this event.
    crawl(db)
    assert len(snapshot(db)["events"]) == 1

    with TestClient(create_app(db)) as client:
        restored = next(
            e
            for e in client.get(f"/evidence?event_id={event_id}").json()
            if e["field"] == "category"
        )
        assert restored["status"] == "Verified"
        assert restored["decidedBy"] == "revenue-manager"
        assert restored["origin"] == f"verification:{review.ORIGIN_HUMAN}"
        stored = client.get(f"/review/{event_id}", headers=WRITER).json()
        assert stored[0]["reviewer"] == "revenue-manager"
        assert stored[0]["note"] == "confirmed as a cultural festival"


def test_a_human_decision_lapses_when_the_value_changes(db):
    """A reviewer must never be recorded as having approved a value they never saw.

    A `category` claim is used because it is a classification rule and therefore never
    auto-verifies: if the field could verify itself, a lapsed human approval would be
    indistinguishable from a fresh rule decision. The category is what changes, not the event
    name, because the name is part of the event fingerprint and renaming would create a
    different event instead of updating this one.
    """
    crawl(db, aggregator=False)
    event_id = snapshot(db)["events"][0]["id"]

    with TestClient(create_app(db)) as client:
        row = next(
            e
            for e in client.get(f"/evidence?event_id={event_id}").json()
            if e["field"] == "category"
        )
        approved_value = row["value"]
        assert row["status"] != "Verified", row
        posted = client.post(
            "/review",
            headers=WRITER,
            json={
                "event_id": event_id,
                "field": "category",
                "decision": "Verified",
                "value": approved_value,
                "reviewer": "rm",
            },
        )
        assert posted.status_code == 200, posted.text
        after_approval = next(
            e
            for e in client.get(f"/evidence?event_id={event_id}").json()
            if e["field"] == "category"
        )
        assert after_approval["status"] == "Verified"
        assert after_approval["decidedBy"] == "rm"

    # The same event is re-announced under a category this source maps differently.
    crawl(db, official_name="2026苏州测试体育赛事", aggregator=False)

    with TestClient(create_app(db)) as client:
        rows = [
            e
            for e in client.get(f"/evidence?event_id={event_id}").json()
            if e["field"] == "category"
        ]
        assert rows, "the event should still exist after the announcement changed"
        current = next((r for r in rows if r["value"] != approved_value), None)
        assert current is not None, (
            "the extracted category should have changed; rows were "
            f"{[(r['value'], r['status']) for r in rows]}"
        )
        # The old approval must not silently carry over to a value it never reviewed.
        assert current["decidedBy"] != "rm", current
        assert current["status"] != "Verified", current
        # The decision itself stays on record, so a reviewer can see it needs repeating.
        stored = client.get(f"/review/{event_id}", headers=WRITER).json()
        assert stored and stored[0]["reviewer"] == "rm"
