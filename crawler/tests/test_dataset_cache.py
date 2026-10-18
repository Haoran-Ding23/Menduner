"""The dataset endpoint: one snapshot, served with a validator so repeat loads are free.

The payload is ~5 MB of JSON (87% of it evidence rows). Every page load used to re-download it
with no way for the browser to ask "is this still the same one?", which on a phone meant an
11-second load against a 10-second client timeout. The ETag makes the second visit a 304 with
no body; it must change as soon as the data does, or a reviewer would keep seeing stale data.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend.database import connect, initialize
from backend.main import create_app
from crawler.demo.adapters.mock import GovernmentEventAdapter, OfficialVenueAdapter
from crawler.demo.legacy import ingest


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "dataset.sqlite3"
    initialize(path)
    ingest(path, [OfficialVenueAdapter(), GovernmentEventAdapter()])
    return path


def test_dataset_is_served_with_a_validator_and_revalidates_to_304(db):
    with TestClient(create_app(db)) as client:
        first = client.get("/dataset")
        assert first.status_code == 200
        assert first.headers["cache-control"] == "no-cache"
        etag = first.headers["etag"]
        assert etag.startswith('"') and len(etag) > 10

        revalidated = client.get("/dataset", headers={"If-None-Match": etag})
        assert revalidated.status_code == 304
        assert revalidated.content == b""
        assert revalidated.headers["etag"] == etag

        # A different validator must still return the body, not a bogus 304.
        changed = client.get("/dataset", headers={"If-None-Match": '"something-else"'})
        assert changed.status_code == 200
        assert changed.json()["events"] == first.json()["events"]


def test_the_validator_changes_when_the_data_changes(db):
    with TestClient(create_app(db)) as client:
        before = client.get("/dataset").headers["etag"]
        with connect(db) as con:
            con.execute(
                "INSERT INTO venues(id, payload) VALUES(?, ?)",
                ("venue-later", json.dumps({"id": "venue-later", "name": "后来加的场馆"},
                                           ensure_ascii=False)),
            )
        after = client.get("/dataset")
        assert after.headers["etag"] != before
        assert any(v["id"] == "venue-later" for v in after.json()["venues"])
        # The old validator must not produce a 304 any more.
        stale = client.get("/dataset", headers={"If-None-Match": before})
        assert stale.status_code == 200
