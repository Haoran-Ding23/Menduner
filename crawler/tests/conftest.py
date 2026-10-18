"""Shared test fixtures.

The write endpoints require an authenticated caller with a configured role (backend/auth.py).
Deployments map logins to roles in a JSON file; tests point MENDUNER_ROLES_PATH at a temporary
file so the suite does not depend on the repository's live mapping.
"""
from __future__ import annotations

import json

import pytest


@pytest.fixture(autouse=True)
def write_roles(tmp_path, monkeypatch):
    """A test role file: the three accounts the API tests use, one per role."""
    path = tmp_path / "roles.json"
    path.write_text(
        json.dumps(
            {
                "users": {
                    "test-reviewer": {"role": "reviewer", "name": "审核员"},
                    "test-admin": {"role": "admin", "name": "管理员"},
                    "test-viewer": {"role": "viewer", "name": "客户只读"},
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MENDUNER_ROLES_PATH", str(path))
    return path
