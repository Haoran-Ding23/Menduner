"""Roles: who may write, and who may only read.

The reviewer required "independent identity plus server-side role mapping" before the pilot, and
the shared login cannot tell a reviewer from a customer. The mapping is a JSON file for now
(backend/roles.json, override with MENDUNER_ROLES_PATH); a missing entry is denied.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend.database import initialize
from backend.main import create_app


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "roles.sqlite3"
    initialize(path)
    return path


def write(client, headers=None):
    """A write that never changes data: the event does not exist, so authorisation shows up as
    404 (allowed, then not found) instead of 401/403 (refused before the handler)."""
    return client.post(
        "/review",
        headers=headers or {},
        json={"event_id": "no-such-event", "field": "name", "decision": "Verified",
              "reviewer": "someone"},
    )


def test_a_reviewer_passes_the_role_check_and_reaches_the_handler(db):
    with TestClient(create_app(db)) as client:
        response = write(client, {"X-Menduner-Login": "test-reviewer"})
        assert response.status_code == 404, response.text
        assert "Event not found" in response.json()["detail"]


def test_an_admin_may_also_review(db):
    with TestClient(create_app(db)) as client:
        assert write(client, {"X-Menduner-Login": "test-admin"}).status_code == 404


def test_a_viewer_is_authenticated_but_forbidden(db):
    with TestClient(create_app(db)) as client:
        response = write(client, {"X-Menduner-Login": "test-viewer"})
        assert response.status_code == 403
        assert "无权执行该操作" in response.json()["detail"]


def test_an_account_missing_from_the_role_file_is_forbidden(db):
    """nginx may hold a credential this file does not authorise; deny rather than assume."""
    with TestClient(create_app(db)) as client:
        response = write(client, {"X-Menduner-Login": "someone-else"})
        assert response.status_code == 403
        assert "没有配置角色" in response.json()["detail"]


def test_an_anonymous_write_is_still_401_not_403(db):
    with TestClient(create_app(db)) as client:
        assert write(client).status_code == 401


def test_the_role_file_is_required_and_its_absence_fails_closed(db, monkeypatch, tmp_path):
    monkeypatch.setenv("MENDUNER_ROLES_PATH", str(tmp_path / "missing.json"))
    with TestClient(create_app(db)) as client:
        response = write(client, {"X-Menduner-Login": "test-reviewer"})
        assert response.status_code == 403
        assert "没有配置角色" in response.json()["detail"]


def test_a_bearer_token_acts_as_admin(db, monkeypatch):
    monkeypatch.setenv("MENDUNER_WRITE_TOKEN", "s3cret")
    with TestClient(create_app(db)) as client:
        response = write(client, {"Authorization": "Bearer s3cret"})
        assert response.status_code == 404


def test_a_malformed_role_file_fails_closed(db, monkeypatch, tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("MENDUNER_ROLES_PATH", str(path))
    with TestClient(create_app(db)) as client:
        assert write(client, {"X-Menduner-Login": "test-reviewer"}).status_code == 403


def test_whoami_reports_the_role_without_raising_for_anonymous_visitors(db):
    with TestClient(create_app(db)) as client:
        anonymous = client.get("/auth/me").json()
        assert anonymous == {"authenticated": False, "login": None, "role": None}

        reviewer = client.get("/auth/me", headers={"X-Menduner-Login": "test-reviewer"}).json()
        assert reviewer["authenticated"] is True
        assert reviewer["login"] == "test-reviewer" and reviewer["role"] == "reviewer"

        unknown = client.get("/auth/me", headers={"X-Menduner-Login": "nobody"}).json()
        assert unknown["authenticated"] is True and unknown["role"] is None


def test_the_role_file_can_be_pointed_elsewhere(db, monkeypatch, tmp_path):
    """A pilot can run its own mapping without editing the tracked file."""
    path = tmp_path / "custom.json"
    path.write_text(json.dumps({"users": {"pilot-reviewer": {"role": "reviewer"}}}),
                    encoding="utf-8")
    monkeypatch.setenv("MENDUNER_ROLES_PATH", str(path))
    with TestClient(create_app(db)) as client:
        assert write(client, {"X-Menduner-Login": "pilot-reviewer"}).status_code == 404
        assert write(client, {"X-Menduner-Login": "test-reviewer"}).status_code == 403
