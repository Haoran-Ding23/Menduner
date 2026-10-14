"""Regression coverage for V1.5 request, publication and audit boundaries."""

import gzip
import json

import httpx
import pytest

from backend.database import connect, snapshot
from crawler.http import MAX_PAGE_BYTES, PublicClient
from crawler.pipeline import run_pipeline
from crawler.sources.base import RealSource
from crawler.storage import put_evidence
from crawler.tests.test_v15 import StaticSource, item, music


def test_decoding_failure_is_audited_without_retry():
    visited = []

    def transport(request):
        visited.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(
            200, stream=httpx.ByteStream(b"invalid gzip"),
            headers={"Content-Type": "text/html", "Content-Encoding": "gzip"},
        )

    client = PublicClient(transport=httpx.MockTransport(transport), interval=0)
    try:
        with pytest.raises(httpx.DecodingError):
            client.get("https://example.test/event")
        assert visited == ["/robots.txt", "/event"]
        audit = client.audit_since()
        assert audit["httpRequests"] == 2
        assert audit["robotsRequests"] == 1 and audit["retriedRequests"] == 0
        assert client.requests[-1]["status"] == 200
        assert client.requests[-1]["error"] and not client.pages
    finally:
        client.close()


def test_same_raw_body_with_different_locators_is_not_a_duplicate(tmp_path):
    raw = json.dumps({"content": [
        {"id": key, "title": "苏州演出 " + key,
         "attributeMapSingle": {"time": {"value": "2026-11-18 19:30"}}}
        for key in ("one", "two")
    ]})

    class Collision(StaticSource):
        def collect(self):
            return [item(raw, "orchestra_json").model_copy(update={"locator": key})
                    for key in ("one", "two")]

    db = tmp_path / "locator.sqlite3"
    report = run_pipeline(db, [Collision()])
    assert report["itemsRejected"] == 2 and report["eventsStored"] == 0
    with connect(db) as con:
        rows = con.execute("SELECT * FROM crawler_raw_items").fetchall()
        assert len(rows) == 2
        assert all(r["validation_status"] == "Rejected" for r in rows)


def test_reusing_client_and_adapter_reports_only_current_job(tmp_path):
    def transport(request):
        return (httpx.Response(404) if request.url.path == "/robots.txt" else
                httpx.Response(200, text=music(), headers={"Content-Type": "text/html"}))

    class FetchingSource(RealSource):
        source_id = "test-fetching"
        source_name = "Test-only fetching"
        source_url = "https://example.test/event"
        kind = "event_platform"

        def collect(self):
            return [self.item(self.fetch(self.source_url))]

    client = PublicClient(transport=httpx.MockTransport(transport), interval=0)
    source = FetchingSource(client=client)
    try:
        first = run_pipeline(tmp_path / "reuse.sqlite3", [source], request_client=client)
        source.errors.append({"error": "previous job failure"})
        source.warnings.append("previous job warning")
        second = run_pipeline(tmp_path / "reuse.sqlite3", [source], request_client=client)
        assert second["status"] == "Success"
        assert second["attempts"][0]["requestErrors"] == second["attempts"][0]["warnings"] == []
        assert first["httpRequests"] == 2 and second["httpRequests"] == 1
        assert second["robotsRequests"] == 0 and len(second["pageLog"]) == 1
        assert second["pagesCollected"] == second["attempts"][0]["pagesCollected"] == 1
        assert second["attempts"][0]["requestAttempts"] == 1
        assert second["eventsStored"] == 1 and second["eventsUpdated"] == 1
    finally:
        client.close()


def test_invalid_merged_date_interval_rolls_back_and_retains_raw(tmp_path):
    raw = music()
    document = json.loads(raw.split(">", 1)[1].rsplit("<", 1)[0])
    document["endDate"] = "2026-11-20"
    raw = '<script type="application/ld+json">' + json.dumps(document) + '</script>'
    db = tmp_path / "dates.sqlite3"
    run_pipeline(db, [StaticSource(), StaticSource("test-real-b", raw)])
    # First merge on the same date, then keep that identity across source updates.
    raw = raw.replace("2026-11-18", "2026-11-19")
    run_pipeline(db, [StaticSource("test-real-b", raw)])
    before = snapshot(db)["events"]
    assert len(before) == 1 and before[0]["verification_status"] == "Conflicting"
    report = run_pipeline(db, [StaticSource(content=music(date="2026-11-21"))])
    assert report["status"] == "Failed" and report["eventsUpdated"] == 0
    assert snapshot(db)["events"] == before
    with connect(db) as con:
        raw = con.execute("SELECT * FROM crawler_raw_items WHERE job_id=?",
                          (report["jobId"],)).fetchone()
        assert raw["validation_status"] == "Failed" and "date interval" in raw["error"]
        assert not con.execute("PRAGMA foreign_key_check").fetchall()


def test_identical_repeated_item_is_counted_once_and_both_raw_records_survive(tmp_path):
    class Repeated(StaticSource):
        def collect(self):
            record = item(music())
            return [record, record]

    db = tmp_path / "repeat.sqlite3"
    report = run_pipeline(db, [Repeated()])
    assert report["status"] == "Success" and report["rawRecordsCollected"] == 2
    assert report["eventsProcessed"] == report["eventsCreated"] == 1
    assert report["duplicatesDetected"] == 1 and report["evidenceRecordsGenerated"] == 10
    with connect(db) as con:
        assert {r[0] for r in con.execute("SELECT validation_status FROM crawler_raw_items")} == {"Published", "Duplicate"}


@pytest.mark.parametrize("compressed", [False, True])
def test_stream_limit_closes_response_and_counts_failed_request(compressed):
    body = b"a" * (MAX_PAGE_BYTES + 1)
    headers = {"Content-Type": "text/html"}
    if compressed:
        body = gzip.compress(body)
        headers["Content-Encoding"] = "gzip"

    class TrackingStream(httpx.SyncByteStream):
        closed = False

        def __iter__(self):
            for start in range(0, len(body), 100_000):
                yield body[start:start + 100_000]

        def close(self):
            self.closed = True

    stream = TrackingStream()

    def transport(request):
        return (httpx.Response(404) if request.url.path == "/robots.txt" else
                httpx.Response(200, stream=stream, headers=headers))

    client = PublicClient(transport=httpx.MockTransport(transport), interval=0)
    try:
        with pytest.raises(ValueError, match="2 MB"):
            client.get("https://example.test/event")
        assert stream.closed and not client.pages
        assert client.audit_since()["httpRequests"] == 2
    finally:
        client.close()


def test_valid_compressed_page_is_decoded_only_once():
    body = music().encode()

    def transport(request):
        return (httpx.Response(404) if request.url.path == "/robots.txt" else
                httpx.Response(200, stream=httpx.ByteStream(gzip.compress(body)),
                               headers={"Content-Type": "text/html; charset=utf-8",
                                        "Content-Encoding": "gzip"}))

    client = PublicClient(transport=httpx.MockTransport(transport), interval=0)
    try:
        page = client.get("https://example.test/event")
        assert page.content == body.decode() and page.metadata["bytes"] == len(body)
    finally:
        client.close()


def test_refresh_preserves_manual_evidence_and_other_source_timestamps(tmp_path, monkeypatch):
    import crawler.pipeline as pipeline

    db = tmp_path / "evidence.sqlite3"
    monkeypatch.setattr(pipeline, "stamp", lambda: "2026-10-13T09:00:00+00:00")
    run_pipeline(db, [StaticSource(), StaticSource("test-real-b")])
    before = snapshot(db)
    event_id = before["events"][0]["id"]
    manual = dict(id="manual-review", entityId=event_id, field="name", value="Review note",
                  status="Needs Review", sourceUrl="https://example.test/review",
                  sourceName="Manual reviewer", method="manual", updatedAt="2026-10-12")
    with connect(db) as con:
        put_evidence(con, manual, event_id)
    monkeypatch.setattr(pipeline, "stamp", lambda: "2026-10-13T10:00:00+00:00")
    report = run_pipeline(db, [StaticSource(content=music(date="2026-11-19"))])
    evidence = snapshot(db)["evidence"]
    assert next(e for e in evidence if e["id"] == "manual-review")["value"] == "Review note"
    assert {e["updatedAt"] for e in evidence if e.get("source") == "test-real-b"} == {"2026-10-13T09:00:00+00:00"}
    assert {e["updatedAt"] for e in evidence if e.get("source") == "test-real-a"} == {"2026-10-13T10:00:00+00:00"}
    assert report["evidenceRecordsGenerated"] == 20 and len(evidence) == 21
    with connect(db) as con:
        assert con.execute("SELECT COUNT(*) FROM crawler_raw_items").fetchone()[0] == 3
        assert not con.execute("PRAGMA foreign_key_check").fetchall()


@pytest.mark.parametrize("status,expected", [("Success", 0), ("Partial", 2), ("Failed", 2)])
def test_cli_passes_audit_client_and_closes_it(monkeypatch, capsys, tmp_path, status, expected):
    import crawler.run as cli
    import sys

    class Client:
        closed = False

        def close(self):
            self.closed = True

    client = Client()
    monkeypatch.setattr(cli, "PublicClient", lambda **kwargs: client)
    monkeypatch.setattr(sys, "argv", ["crawler.run", "--source", "government", "--db", str(tmp_path / "cli.sqlite3")])

    def pipeline(path, adapters, *, request_client):
        assert request_client is client and len(adapters) == 1
        assert adapters[0].client is client
        return {"status": status}

    monkeypatch.setattr(cli, "run_pipeline", pipeline)
    assert cli.main() == expected and client.closed
    assert json.loads(capsys.readouterr().out)["status"] == status
