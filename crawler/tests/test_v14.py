import json
import sqlite3
from copy import deepcopy
import pytest
from fastapi.testclient import TestClient
from backend.database import connect, initialize, snapshot
from backend.main import create_app
from crawler.pipeline import run_pipeline as _run_pipeline

def run_pipeline(*args, **kwargs):
    return _run_pipeline(*args, allow_demo=True, **kwargs)

from crawler.demo.sources import SOURCES
from crawler.demo.sources.venue import VenueSource
from crawler.demo.sources.event_platform import EventPlatformSource
from crawler.demo.sources.government import SuzhouGovernmentSource
from crawler.schema import CollectedItem
from crawler.demo.run import SimulatedFailure
from crawler.demo.legacy import ingest
from crawler.demo.adapters.mock import OfficialVenueAdapter, GovernmentEventAdapter


@pytest.fixture
def db(tmp_path):
    return tmp_path / "pipeline.sqlite3"


def sources():
    return [cls() for cls in SOURCES.values()]


def rows(db, table):
    with connect(db) as con:
        return [dict(r) for r in con.execute(f"SELECT * FROM {table}")]


def test_independent_source_contracts_keep_original_material():
    for adapter in sources():
        records = adapter.collect()
        assert records and all(isinstance(r, CollectedItem) for r in records)
        for item in records:
            assert item.original_url.startswith(adapter.source_url)
            assert item.original_url.split("/")[2].endswith(".invalid")
            assert item.source_name == adapter.source_name
            assert item.crawl_time.tzinfo
            assert isinstance(json.loads(item.raw_content), dict)


def test_roundtrip_dedup_and_api_compatibility(db):
    report = run_pipeline(db, sources())
    assert report["status"] == "Success"
    assert (
        report["eventsProcessed"],
        report["eventsCreated"],
        report["duplicatesDetected"],
        report["eventsStored"],
    ) == (13, 11, 2, 11)
    assert len(rows(db, "crawler_raw_items")) == 13
    unified = rows(db, "crawler_unified_events")
    assert all(
        set(
            [
                "event_id",
                "event_name",
                "category",
                "start_date",
                "end_date",
                "venue",
                "location",
                "organizer",
                "source_url",
            ]
        )
        <= json.loads(r["normalized_json"]).keys()
        for r in unified
    )
    with TestClient(create_app(db)) as client:
        data = client.get("/dataset").json()
        assert data["status"]["sourceCount"] == 3 and data["status"]["eventCount"] == 11
        assert data["status"]["verificationCounts"]["Verified"] == 0
        evidence = client.get("/evidence?event_id=demo-01").json()
        assert {e["source"] for e in evidence} == {"mock-venue", "mock-platform"}
        assert all(e["raw_item_id"] and 0 <= e["confidence"] <= 1 for e in evidence)
        assert client.get("/events/demo-01").json()["venueId"] == "v-expo"
        assert client.get("/events/platform-01").status_code == 404


def test_repeat_runs_keep_current_entities_and_append_raw_history(db):
    run_pipeline(db, sources())
    before = snapshot(db)
    result = run_pipeline(db, sources())
    after = snapshot(db)
    assert result["eventsCreated"] == 0 and result["eventsStored"] == 11
    assert [e["id"] for e in before["events"]] == [e["id"] for e in after["events"]]
    assert len(before["evidence"]) == len(after["evidence"])
    assert len(rows(db, "crawler_observations")) == 13
    assert len(rows(db, "crawler_raw_items")) == 26
    assert len(rows(db, "crawler_jobs")) == 2
    assert after["status"]["revision"] == before["status"]["revision"] + 1


def test_existing_source_item_updates_stable_event_and_preserves_other_sources(db):
    run_pipeline(db, sources())

    class Updated(VenueSource):
        def collect(self):
            result = super().collect()
            item = result[1]
            raw = json.loads(item.raw_content)
            raw["title"] = "DEMO updated academic forum"
            raw["begin"] = "2026-10-21"
            raw["finish"] = "2026-10-22"
            result[1] = item.model_copy(update={"raw_content": json.dumps(raw)})
            return result

    result = run_pipeline(db, [Updated()])
    assert result["eventsStored"] == 11 and result["eventsCreated"] == 0
    event = next(e for e in snapshot(db)["events"] if e["id"] == "demo-03")
    assert (
        event["name"] == "DEMO updated academic forum"
        and event["startDate"] == "2026-10-21"
    )
    assert any(e["id"] == "platform-03" for e in snapshot(db)["events"])


def test_conflicts_keep_both_observations_unresolved(db):
    run_pipeline(db, sources())
    candidates = [
        r
        for r in rows(db, "crawler_evidence")
        if r["event_id"] == "demo-02" and r["field_name"] == "end_date"
    ]
    assert {json.loads(r["value"]) for r in candidates} == {"2026-10-18", "2026-10-19"}
    assert all(r["verification_status"] == "Conflicting" for r in candidates)
    event = next(e for e in snapshot(db)["events"] if e["id"] == "demo-02")
    assert (
        event["endDate"] == "2026-10-18"
        and event["verification_status"] == "Conflicting"
    )
    assert all(
        r["verification_status"] != "Verified" for r in rows(db, "crawler_evidence")
    )


def test_source_failure_keeps_previous_records_and_continues(db):
    run_pipeline(db, sources())
    before = {
        r["item_key"]: r["normalized_json"]
        for r in rows(db, "crawler_observations")
        if r["source_id"] == "mock-government"
    }
    report = run_pipeline(
        db,
        [
            SimulatedFailure(SuzhouGovernmentSource()),
            VenueSource(),
            EventPlatformSource(),
        ],
    )
    assert report["status"] == "Partial" and report["sourcesProcessed"] == 2
    after = {
        r["item_key"]: r["normalized_json"]
        for r in rows(db, "crawler_observations")
        if r["source_id"] == "mock-government"
    }
    assert before == after
    assert any(
        a["status"] == "Failed" and "Simulated" in a["error"]
        for a in rows(db, "crawler_attempts")
    )


def test_invalid_item_is_retained_raw_but_not_published(db):
    class Invalid(VenueSource):
        def collect(self):
            result = super().collect()
            item = result[0]
            raw = json.loads(item.raw_content)
            raw["begin"] = "2026-02-30"
            result[0] = item.model_copy(update={"raw_content": json.dumps(raw)})
            return result

    report = run_pipeline(db, [Invalid(), SuzhouGovernmentSource()])
    assert report["status"] == "Partial" and report["itemsRejected"] == 1
    rejected = [
        r for r in rows(db, "crawler_raw_items") if r["validation_status"] == "Rejected"
    ]
    assert (
        len(rejected) == 1
        and "2026-02-30" in rejected[0]["raw_content"]
        and rejected[0]["error"]
    )
    assert not any(e["id"] == "demo-01" for e in snapshot(db)["events"])


def test_incompatible_repeated_source_key_is_rejected_without_overwrite(db):
    class Collision(VenueSource):
        def collect(self):
            items = super().collect()
            changed = json.loads(items[0].raw_content)
            changed["title"] = "Other event"
            return [
                items[0],
                items[0].model_copy(update={"raw_content": json.dumps(changed)}),
            ]

    report = run_pipeline(db, [Collision()])
    assert report["itemsRejected"] == 2 and report["eventsStored"] == 0
    assert len(rows(db, "crawler_raw_items")) == 2


def test_unknown_dates_do_not_merge_and_distinct_occurrences_remain_separate(db):
    class Occurrences(EventPlatformSource):
        def collect(self):
            item = super().collect()[0]
            raw = json.loads(item.raw_content)
            unknown = deepcopy(raw)
            unknown.update(id="unknown-a", start=None, end=None)
            unknown_b = dict(unknown, id="unknown-b")
            later = dict(raw, id="later", start="2026-11-12", end="2026-11-15")
            return [
                item.model_copy(
                    update={
                        "item_key": r["id"],
                        "raw_content": json.dumps(r),
                        "original_url": self.source_url + "/" + r["id"],
                    }
                )
                for r in [raw, unknown, unknown_b, later]
            ]

    report = run_pipeline(db, [Occurrences()])
    assert report["eventsStored"] == 4 and report["duplicatesDetected"] == 0


def test_old_database_migration_is_additive_and_preserves_existing_ids(db):
    ingest(db, [OfficialVenueAdapter(), GovernmentEventAdapter()])
    with connect(db) as con:
        for table in [
            "crawler_evidence",
            "crawler_unified_events",
            "crawler_observations",
            "crawler_raw_items",
            "crawler_attempts",
            "crawler_jobs",
        ]:
            con.execute(f"DROP TABLE {table}")
        columns = [r["name"] for r in con.execute("PRAGMA table_info(events)")]
    initialize(db)
    initialize(db)
    assert len(snapshot(db)["events"]) == 10
    run_pipeline(db, sources())
    assert {e["id"] for e in snapshot(db)["events"]} == {
        f"demo-{i:02}" for i in range(1, 11)
    } | {"platform-03"}
    with connect(db) as con:
        assert [r["name"] for r in con.execute("PRAGMA table_info(events)")] == columns


def test_event_write_failure_rolls_back_source_and_keeps_raw_history(db, monkeypatch):
    import crawler.pipeline as pipeline

    original = pipeline.refresh_event

    def broken(con, event_id, now, source_meta=None):
        if event_id == "demo-03":
            raise sqlite3.OperationalError("simulated persistence error")
        if source_meta is None:
            # The pipeline must thread per-source metadata into refresh_event; if it stops
            # doing that, the auto-verification rule silently loses its authority gate.
            # Fail loudly rather than letting this test pass for the wrong reason.
            raise AssertionError("source_meta was not threaded into refresh_event")
        original(con, event_id, now, source_meta)

    monkeypatch.setattr(pipeline, "refresh_event", broken)
    report = run_pipeline(db, [VenueSource(), SuzhouGovernmentSource()])
    assert report["status"] == "Partial"
    # A failed publish() attempt must be atomic: the events it created before the failure
    # are withdrawn along with their observations, so nothing keeps the failed source's id.
    assert not any(e["source"] == "mock-venue" for e in snapshot(db)["events"])
    assert (
        len(
            [
                r
                for r in rows(db, "crawler_raw_items")
                if r["validation_status"] == "Failed"
            ]
        )
        == 5
    )
    assert len(snapshot(db)["events"]) == 5


def test_mock_ingestion_cannot_overwrite_real_event(db):
    ingest(db, [OfficialVenueAdapter(), GovernmentEventAdapter()])
    with connect(db) as con:
        row = con.execute("SELECT * FROM events WHERE id=?", ("demo-01",)).fetchone()
        payload = json.loads(row["payload"])
        payload["demo"] = False
        con.execute(
            "UPDATE events SET payload=? WHERE id=?", (json.dumps(payload), "demo-01")
        )
    report = run_pipeline(db, [VenueSource()])
    assert report["status"] == "Failed"
    real = next(e for e in snapshot(db)["events"] if e["id"] == "demo-01")
    assert real["demo"] is False
    assert len(snapshot(db)["events"]) == 10
