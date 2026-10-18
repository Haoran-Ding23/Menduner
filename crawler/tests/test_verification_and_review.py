"""The auto-verification rule and the human review workflow.

These tests are the contract for V1.6.3: a field is auto-verified only from an official
source with deterministic extraction, everything else is queued for a human, and a human
decision survives the next crawl.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend.database import connect, initialize, snapshot
from backend.main import create_app
from crawler import review, verification
from crawler.demo.adapters.mock import GovernmentEventAdapter, OfficialVenueAdapter
from crawler.demo.legacy import ingest


@pytest.fixture
def db(tmp_path):
    return tmp_path / "review.sqlite3"


# Write endpoints require an authenticated caller (nginx forwards its login here in
# production). Tests send the same header the proxy sets; one test below asserts the refusal.
WRITER = {"X-Menduner-Login": "test-reviewer"}


def adapters():
    return [OfficialVenueAdapter(), GovernmentEventAdapter()]


# --- the rule itself ---------------------------------------------------------

def test_official_source_with_deterministic_extraction_is_verified():
    decision = verification.decide(
        field="start_date",
        value="2026-11-18",
        method="explicit_source_field",
        trust_level="OFFICIAL_GOVERNMENT",
    )
    assert decision.verified and decision.status == "Verified"
    assert decision.origin == verification.AUTO_ORIGIN


def test_rule_verifies_only_official_plus_deterministic():
    """The documented rule: BOTH authority and determinism are required."""
    cases = [
        # (trust, method, expected)
        ("OFFICIAL_GOVERNMENT", "explicit_source_field", "Verified"),
        ("OFFICIAL_VENUE", "JSON-LD.event_datetime", "Verified"),
        ("OFFICIAL_VENUE", "explicit_itemprop_startDate_year", "Verified"),
        # authoritative source, but the value was produced by a rule
        ("OFFICIAL_GOVERNMENT", "article_headline_to_event_name", "Needs Review"),
        ("OFFICIAL_VENUE", "explicit_title_keyword_to_category_rule", "Needs Review"),
        # clean extraction, but the publisher is not the organiser
        ("COMMERCIAL_PLATFORM", "explicit_source_field", "Needs Review"),
        ("SECONDARY_MEDIA", "explicit_labelled_detail_time (YYYY-MM-DD)", "Needs Review"),
        # unknown authority fails closed
        (None, "explicit_source_field", "Needs Review"),
    ]
    for trust, method, expected in cases:
        got = verification.decide(
            field="start_date", value="2026-11-18", method=method, trust_level=trust
        )
        assert got.status == expected, (trust, method, got)


def test_heuristic_marker_beats_an_explicit_looking_method_name():
    decision = verification.decide(
        field="start_date",
        value="2026-11-18",
        method="explicit_title_keyword_to_category_rule",
        trust_level="OFFICIAL_GOVERNMENT",
    )
    assert not decision.verified and "not deterministic" in decision.reason


def test_derived_and_non_factual_fields_are_never_auto_verified():
    """A response URL and a derived reference id are bookkeeping, not fact claims."""
    for field in ("source_url", "venue_id", "district_id", "category"):
        decision = verification.decide(
            field=field,
            value="x",
            method="explicit_source_field",
            trust_level="OFFICIAL_GOVERNMENT",
        )
        assert not decision.verified, field
        assert "derived" in decision.reason or "not an auto-verifiable" in decision.reason


def test_mock_sources_are_never_verified():
    decision = verification.decide(
        field="event_name",
        value="synthetic",
        method="explicit_source_field",
        trust_level="OFFICIAL_GOVERNMENT",
        mock=True,
    )
    assert decision.status == "Unverified" and not decision.verified


def test_a_contradiction_is_never_auto_verified_even_from_an_official_source():
    decision = verification.decide(
        field="end_date",
        value="2026-11-18",
        method="explicit_source_field",
        trust_level="OFFICIAL_GOVERNMENT",
        existing_status="Conflicting",
    )
    assert decision.status == "Conflicting" and not decision.verified


def test_absent_value_is_missing_not_verified():
    decision = verification.decide(
        field="organizer",
        value=None,
        method="explicit_source_field",
        trust_level="OFFICIAL_VENUE",
    )
    assert decision.status == "Missing" and not decision.verified


def test_every_declared_deterministic_shape_is_accepted_and_heuristics_are_not():
    """The rule keys off the codebase's own ``explicit_*`` / ``official_*`` naming, so a
    newly added explicit extractor is verified without editing this module — while a
    rule-based method can never slip through, even if named ``explicit_..._rule``."""
    for method in (
        "explicit_source_field",
        "explicit_leading_event_date",
        "explicit_named_event_in_article",
        "explicit_labelled_opening_date (publication timestamps never substituted)",
        "explicit_itemprop_startDate_year",
        "official_labelled_activity_date",
        "official_labelled_activity_location",
        "JSON-LD.event_datetime",
        "detail_page_heading",
        "named_place_before_source_street_part",
    ):
        assert verification.is_deterministic(method), method
    for method in (
        None,
        "",
        "guess",
        "category_rule",
        "event_category_rule",
        "explicit_title_keyword_to_category_rule",
        "article_headline_to_event_name",
        "derived_reference_id_from_explicit_venue_name",
        "source_topic_to_category_rule",
        "unknown_new_rule",
    ):
        assert not verification.is_deterministic(method), method


def test_derived_reference_method_is_never_deterministic_even_though_it_says_explicit():
    """``derived_reference_id_from_explicit_venue_name`` contains the word "explicit" but is
    a derived reference id, not a fact claim, and must not be auto-verified."""
    assert not verification.is_deterministic(
        "derived_reference_id_from_explicit_venue_name"
    )


# --- the durable store -------------------------------------------------------

def test_human_decisions_survive_a_full_evidence_rebuild(db):
    """The pipeline DELETEs and re-inserts field evidence on every crawl. A human decision
    written into an evidence row would be destroyed; it lives in its own table instead."""
    initialize(db)
    ingest(db, adapters())
    before = snapshot(db)
    event_id = before["events"][0]["id"]
    field = "name"

    with TestClient(create_app(db)) as client:
        evidence = client.get(f"/evidence?event_id={event_id}").json()
        current = next(e for e in evidence if e["field"] == field)
        posted = client.post(
            "/review",
            headers=WRITER,
            json={
                "event_id": event_id,
                "field": field,
                "decision": "Verified",
                "value": current["value"],
                "reviewer": "revenue-manager",
                "note": "checked against the venue poster",
            },
        )
        assert posted.status_code == 200, posted.text
        assert posted.json()["decision"] == "Verified"
        stored = client.get(f"/review/{event_id}").json()
        assert stored[0]["field"] == field and stored[0]["reviewer"] == "revenue-manager"

    # Simulate the next crawl: the whole evidence set is thrown away and rebuilt.
    ingest(db, adapters())
    assert len(snapshot(db)["events"]) == len(before["events"])
    with connect(db) as con:
        still_there = review.decisions_for(con, event_id)
    assert still_there[field]["reviewer"] == "revenue-manager"


def test_a_decision_does_not_apply_to_a_value_the_reviewer_never_saw():
    """If a later crawl extracts a different value, the review must be repeated."""
    decision = {
        "decision": review.APPROVE,
        "reviewed_value": review.normalized("2026-11-18"),
    }
    assert review.resolve(decision, "2026-11-18") == ("Verified", "2026-11-18")
    assert review.resolve(decision, "2026-11-19") is None


def test_a_correction_replaces_the_value_and_verifies_it():
    decision = {
        "decision": review.CORRECT,
        "reviewed_value": review.normalized("2026-11-18"),
        "corrected_value": review.normalized("2026-11-19"),
    }
    status, value = review.resolve(decision, "2026-11-18")
    assert status == "Verified" and value == "2026-11-19"


def test_rejection_keeps_the_claim_out_of_verified_without_deleting_it():
    decision = {"decision": review.REJECT, "reviewed_value": review.normalized("2026-11-18")}
    assert review.resolve(decision, "2026-11-18") == ("Needs Review", "2026-11-18")


def test_a_correction_must_carry_a_value(db):
    initialize(db)
    ingest(db, adapters())
    event_id = snapshot(db)["events"][0]["id"]
    with TestClient(create_app(db)) as client:
        bad = client.post(
            "/review",
            headers=WRITER,
            json={
                "event_id": event_id,
                "field": "name",
                "decision": "Corrected",
                "reviewer": "rm",
            },
        )
        assert bad.status_code == 400
        unknown = client.post(
            "/review",
            headers=WRITER,
            json={
                "event_id": event_id,
                "field": "name",
                "decision": "Looks Fine",
                "reviewer": "rm",
            },
        )
        assert unknown.status_code == 400
        missing = client.post(
            "/review",
            headers=WRITER,
            json={
                "event_id": "does-not-exist",
                "field": "name",
                "decision": "Verified",
                "reviewer": "rm",
            },
        )
        assert missing.status_code == 404


def test_a_write_without_a_login_is_refused(db):
    """The reported defect: POST /review answered 200 to an anonymous caller."""
    initialize(db)
    ingest(db, adapters())
    event_id = snapshot(db)["events"][0]["id"]
    with TestClient(create_app(db)) as client:
        attempts = [
            ("post", "/review", {"event_id": event_id, "field": "name",
                                 "decision": "Verified", "reviewer": "anonymous"}),
            ("post", "/review/event", {"event_id": event_id, "reviewer": "anonymous"}),
            ("delete", f"/review/{event_id}/name", None),
            ("post", "/venues/merge", {"alias_id": "a", "canonical_id": "b",
                                       "reviewer": "anonymous", "reason": "x"}),
            ("post", "/venues/coordinates", {"venue_id": "a", "lng": 120.6, "lat": 31.3,
                                             "reviewer": "anonymous"}),
        ]
        for method, path, body in attempts:
            response = (
                client.post(path, json=body) if method == "post" else client.delete(path)
            )
            assert response.status_code == 401, (method, path, response.text)
            assert "写操作需要身份" in response.json()["detail"]
    # Nothing was recorded by a refused write.
    with connect(db) as con:
        tables = {row[0] for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if "review_decisions" in tables:
            assert con.execute("SELECT COUNT(*) FROM review_decisions").fetchone()[0] == 0


def test_a_bearer_token_authorises_a_script_without_a_login(db, monkeypatch):
    initialize(db)
    ingest(db, adapters())
    event_id = snapshot(db)["events"][0]["id"]
    monkeypatch.setenv("MENDUNER_WRITE_TOKEN", "s3cret-token")
    with TestClient(create_app(db)) as client:
        refused = client.post(
            "/review",
            headers={"Authorization": "Bearer wrong"},
            json={"event_id": event_id, "field": "name", "decision": "Verified",
                  "reviewer": "script"},
        )
        assert refused.status_code == 401
        accepted = client.post(
            "/review",
            headers={"Authorization": "Bearer s3cret-token"},
            json={"event_id": event_id, "field": "name", "decision": "Verified",
                  "reviewer": "script"},
        )
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["authenticated_as"] == "token"


def test_a_review_without_a_value_binds_to_the_stored_claim(db):
    """A value-less approval must bind to what was on screen, not to everything after it.

    It used to store reviewed_value=NULL, which ``resolve`` read as "matches any value": one
    approval kept verifying every later value nobody had looked at.
    """
    initialize(db)
    ingest(db, adapters())
    event_id = snapshot(db)["events"][0]["id"]
    with TestClient(create_app(db)) as client:
        current = next(
            e for e in client.get(f"/evidence?event_id={event_id}").json()
            if e["field"] == "name"
        )
        posted = client.post(
            "/review",
            headers=WRITER,
            json={"event_id": event_id, "field": "name", "decision": "Verified",
                  "reviewer": "rm"},
        )
        assert posted.status_code == 200, posted.text
        assert posted.json()["reviewed_value"] == review.normalized(current["value"]), (
            "the decision must carry the claim it reviewed"
        )


def test_a_stale_value_is_refused_instead_of_verifying_an_unseen_claim(db):
    initialize(db)
    ingest(db, adapters())
    event_id = snapshot(db)["events"][0]["id"]
    with TestClient(create_app(db)) as client:
        stale = client.post(
            "/review",
            headers=WRITER,
            json={"event_id": event_id, "field": "name", "decision": "Verified",
                  "value": "a value that is not the current claim", "reviewer": "rm"},
        )
        assert stale.status_code == 409
        assert "证据已变化" in stale.json()["detail"]


def test_a_decision_for_an_absent_claim_lapses_when_a_value_appears():
    """The same rule at the resolution layer, for decisions already in the table."""
    unbound = {"decision": review.APPROVE, "reviewed_value": None}
    assert review.resolve(unbound, None) == ("Verified", None)
    assert review.resolve(unbound, "") == ("Verified", "")
    assert review.resolve(unbound, "a later value") is None
    assert review.resolve(unbound, "2026-11-19") is None


def test_review_can_be_withdrawn(db):
    initialize(db)
    ingest(db, adapters())
    event_id = snapshot(db)["events"][0]["id"]
    with TestClient(create_app(db)) as client:
        client.post(
            "/review",
            headers=WRITER,
            json={
                "event_id": event_id,
                "field": "name",
                "decision": "Verified",
                "reviewer": "rm",
            },
        )
        assert client.get(f"/review/{event_id}").json()
        removed = client.delete(f"/review/{event_id}/name", headers=WRITER)
        assert removed.json()["removed"] == 1
        assert client.get(f"/review/{event_id}").json() == []
        assert client.get("/review").json() == []
