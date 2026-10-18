"""The internal business-plan document and its admin-only API.

The panel contains price assumptions and customer names. It is not public data: reading it and
writing it both require the admin role, and the stored document records who saved it.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend import business_plan
from backend.database import connect, initialize
from backend.main import create_app

ADMIN = {"X-Menduner-Login": "test-admin"}
REVIEWER = {"X-Menduner-Login": "test-reviewer"}
VIEWER = {"X-Menduner-Login": "test-viewer"}

SAMPLE = {
    "pricing": {"proMonthly": 980, "enterpriseMonthly": 780, "trialIssues": 4},
    "costs": {"server": 300, "data": 200, "operations": 6000},
    "pipeline": [{"id": "pl1", "hotel": "苏州洲际酒店", "stage": "未接触"}],
    "hypotheses": [],
    "milestones": [],
}


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "plan.sqlite3"
    initialize(path)
    return path


def test_the_plan_starts_empty_so_the_panel_can_show_its_defaults(db):
    with TestClient(create_app(db)) as client:
        response = client.get("/plan", headers=ADMIN)
        assert response.status_code == 200
        assert response.json() == {"document": None, "updatedAt": None, "updatedBy": None}


def test_the_plan_is_admin_only(db):
    with TestClient(create_app(db)) as client:
        assert client.get("/plan").status_code == 401
        assert client.get("/plan", headers=VIEWER).status_code == 403
        assert client.get("/plan", headers=REVIEWER).status_code == 403
        for headers in ({}, VIEWER, REVIEWER):
            response = client.put("/plan", headers=headers, json={"document": SAMPLE})
            assert response.status_code in (401, 403), (headers, response.text)


def test_an_admin_saves_and_reads_the_whole_document(db):
    with TestClient(create_app(db)) as client:
        saved = client.put("/plan", headers=ADMIN, json={"document": SAMPLE})
        assert saved.status_code == 200, saved.text
        body = saved.json()
        assert body["document"] == SAMPLE
        assert body["updatedBy"] == "test-admin"
        assert body["updatedAt"]

        reloaded = client.get("/plan", headers=ADMIN).json()
        assert reloaded["document"] == SAMPLE
        assert reloaded["updatedBy"] == "test-admin"

    # Persisted in the database, not in process memory: a second app instance sees it.
    with TestClient(create_app(db)) as client:
        assert client.get("/plan", headers=ADMIN).json()["document"] == SAMPLE


def test_saving_replaces_the_document_rather_than_merging_it(db):
    with TestClient(create_app(db)) as client:
        client.put("/plan", headers=ADMIN, json={"document": SAMPLE})
        replacement = {"pricing": {"proMonthly": 1200}}
        saved = client.put("/plan", headers=ADMIN, json={"document": replacement})
        assert saved.status_code == 200
        assert client.get("/plan", headers=ADMIN).json()["document"] == replacement


def test_an_oversized_document_is_refused(db):
    small_limit = business_plan.MAX_BYTES
    huge = {"pricing": {"proMonthly": 980}, "blob": "x" * small_limit}
    with TestClient(create_app(db)) as client:
        response = client.put("/plan", headers=ADMIN, json={"document": huge})
        assert response.status_code == 400
        assert "limited to" in response.json()["detail"]


def test_an_empty_document_is_refused(db):
    with TestClient(create_app(db)) as client:
        response = client.put("/plan", headers=ADMIN, json={"document": {}})
        assert response.status_code == 400
        assert "non-empty" in response.json()["detail"]


def test_the_document_is_stored_as_json_and_keeps_unicode(db):
    """The pipeline holds Chinese hotel names; they must round-trip unchanged."""
    with connect(db) as con:
        business_plan.save(con, SAMPLE, updated_by="test-admin")
        payload = con.execute("SELECT payload FROM business_plan").fetchone()["payload"]
    assert json.loads(payload)["pipeline"][0]["hotel"] == "苏州洲际酒店"
