import json
import sqlite3
from pathlib import Path
import httpx
import pytest
from backend.database import connect, initialize, snapshot
from crawler.schema import CollectedItem
from crawler.http import PublicClient
from crawler.extractor import extract
from crawler.pipeline import run_pipeline
from crawler.demo.sources import SOURCES as DEMO
from crawler.sources.base import RealSource
from datetime import datetime, timezone


def music(
    name="苏州测试音乐会",
    venue="苏州文化艺术中心·大剧院",
    date="2026-11-18T19:30:00+08:00",
):
    data = {
        "@type": "MusicEvent",
        "name": name,
        "startDate": date,
        "location": {
            "name": venue,
            "address": {"streetAddress": "苏州测试路1号", "addressLocality": "Suzhou"},
        },
    }
    return (
        '<script type="application/ld+json">'
        + json.dumps(data, ensure_ascii=False)
        + "</script>"
    )


def item(raw, extractor="jsonld", key="stable"):
    return CollectedItem(
        item_key=key,
        original_url="https://example.test/event",
        source_name="Test-only source",
        crawl_time=datetime.now(timezone.utc),
        raw_content=raw,
        extractor=extractor,
        mock=False,
    )


class StaticSource:
    mock = False
    kind = "event_platform"
    source_url = "https://example.test/"

    def __init__(self, source_id="test-real-a", content=None):
        self.source_id = source_id
        self.source_name = "Test-only " + source_id
        self.content = content or music()

    def collect(self):
        return [item(self.content)]


@pytest.fixture
def db(tmp_path):
    return tmp_path / "events.sqlite3"


def test_request_retry_and_robots_without_mock_fallback():
    attempts = []

    def transport(request):
        attempts.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(
                200,
                text="User-agent: *\nAllow: /",
                headers={"Content-Type": "text/plain"},
            )
        if attempts.count("/event") == 1:
            return httpx.Response(503, text="temporary")
        return httpx.Response(200, text=music(), headers={"Content-Type": "text/html"})

    client = PublicClient(
        transport=httpx.MockTransport(transport), interval=0, sleep=lambda n: None
    )
    try:
        page = client.get("https://example.test/event")
        assert attempts.count("/event") == 2
        assert page.metadata["status"] == 200 and len(client.pages) == 1
    finally:
        client.close()


def test_robots_denial_never_requests_restricted_page():
    visited = []

    def transport(request):
        visited.append(request.url.path)
        return httpx.Response(
            200,
            text="User-agent: *\nDisallow: /private",
            headers={"Content-Type": "text/plain"},
        )

    client = PublicClient(
        transport=httpx.MockTransport(transport), interval=0, sleep=lambda n: None
    )
    try:
        with pytest.raises(RuntimeError, match="disallows"):
            client.get("https://example.test/private")
        assert visited == ["/robots.txt"]
    finally:
        client.close()


def test_cross_host_redirect_and_long_retry_delay_are_not_bypassed():
    def transport(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.url.path == "/redirect":
            return httpx.Response(302, headers={"Location": "https://other.test/page"})
        return httpx.Response(429, headers={"Retry-After": "60"})

    client = PublicClient(
        transport=httpx.MockTransport(transport), interval=0, sleep=lambda n: None
    )
    try:
        with pytest.raises(RuntimeError, match="Cross-host"):
            client.get("https://example.test/redirect")
        with pytest.raises(RuntimeError, match="longer retry"):
            client.get("https://example.test/rate")
    finally:
        client.close()


def test_government_publication_date_is_not_event_date():
    raw = '<h1>2026苏州文化节启幕</h1><span>时间：2026-10-12</span><div id="zoomcon"><p>市民可关注未来活动信息。</p></div>'
    event = extract(item(raw, "government_article"), "government")
    assert event["start_date"] is None and event["end_date"] is None
    assert event["organizer"] is None


def test_government_month_day_year_inference_requires_review():
    raw = '<h1>2026苏州文化节启幕</h1><div id="zoomcon"><p>10月10日至10月19日，在苏州工业园区测试街区启幕。</p></div>'
    event = extract(item(raw, "government_article"), "government")
    assert event["start_date"] == "2026-10-10" and event["end_date"] == "2026-10-19"
    assert event["field_evidence"]["start_date"]["status"] == "Needs Review"


def test_jsonld_missing_end_and_organizer_remain_null():
    event = extract(item(music()), "event_platform")
    assert event["start_date"] == "2026-11-18"
    assert event["end_date"] is None and event["organizer"] is None
    assert event["field_evidence"]["start_date"]["status"] == "Unverified"
    assert event["field_evidence"]["category"]["status"] == "Needs Review"


def test_orchestra_ignores_publication_date_and_random_calendar_fields():
    record = {
        "id": "one",
        "title": "苏州测试演出",
        "publishTime": "2026-10-01",
        "attributeMapSingle": {"address": {"value": "金鸡湖音乐会"}},
        "content": "<p>无明确日期地点</p>",
    }
    event = extract(
        item(json.dumps({"content": [record]}), "orchestra_json").model_copy(
            update={"locator": "one"}
        ),
        "venue",
    )
    assert event["start_date"] is None and event["venue"] is None


def test_real_pipeline_has_no_demo_and_keeps_evidence_snippets(db):
    report = run_pipeline(db, [StaticSource()])
    assert report["mode"] == "REAL" and report["eventsStored"] == 1
    data = snapshot(db)
    assert all(not e["demo"] for e in data["events"])
    assert data["status"]["mockSourceCount"] == 0
    evidence = [e for e in data["evidence"] if e["event_id"]]
    assert all(e["status"] != "Verified" for e in evidence)
    assert any(e["snippet"] and "JSON-LD" in e["snippet"] for e in evidence)
    with connect(db) as con:
        assert con.execute("SELECT mock FROM crawler_raw_items").fetchone()["mock"] == 0


def test_real_dedup_and_update_keep_event_identity(db):
    report = run_pipeline(
        db,
        [
            StaticSource(),
            StaticSource("test-real-b", music(venue="苏州文化艺术中心大剧院")),
        ],
    )
    assert report["eventsStored"] == 1 and report["duplicatesDetected"] == 1
    event_id = snapshot(db)["events"][0]["id"]
    report = run_pipeline(
        db, [StaticSource(content=music(date="2026-11-19T19:30:00+08:00"))]
    )
    assert report["eventsStored"] == 1 and snapshot(db)["events"][0]["id"] == event_id
    assert snapshot(db)["events"][0]["verification_status"] == "Conflicting"


def test_demo_is_archived_and_removed_but_backup_contains_original(db):
    demo = run_pipeline(db, [cls() for cls in DEMO.values()], allow_demo=True)
    assert demo["eventsStored"] == 11
    report = run_pipeline(db, [StaticSource()])
    assert report["demoArchive"] and Path(report["demoArchive"]).exists()
    assert (
        snapshot(db)["status"]["eventCount"] == 1
        and snapshot(db)["status"]["mockSourceCount"] == 0
    )
    assert snapshot(report["demoArchive"])["status"]["eventCount"] == 11


def test_production_rejects_demo_source(db):
    report = run_pipeline(db, [next(iter(DEMO.values()))()])
    assert report["status"] == "Failed" and report["eventsStored"] == 0


def test_v14_raw_constraint_migration_preserves_records_and_foreign_keys(db):
    run_pipeline(db, [cls() for cls in DEMO.values()], allow_demo=True)
    with connect(db) as con:
        original_ids = [
            r["id"] for r in con.execute("SELECT id FROM crawler_raw_items")
        ]
        sql = con.execute(
            "SELECT sql FROM sqlite_master WHERE name='crawler_raw_items'"
        ).fetchone()["sql"]
        sql = sql.replace("crawler_raw_items", "legacy_raw", 1).replace(
            "mock IN (0,1)", "mock=1"
        )
        con.execute("PRAGMA foreign_keys=OFF")
        con.executescript(
            sql
            + "; INSERT INTO legacy_raw SELECT * FROM crawler_raw_items; DROP TABLE crawler_raw_items; ALTER TABLE legacy_raw RENAME TO crawler_raw_items;"
        )
    initialize(db)
    initialize(db)
    with connect(db) as con:
        assert original_ids == [
            r["id"] for r in con.execute("SELECT id FROM crawler_raw_items")
        ]
        assert not con.execute("PRAGMA foreign_key_check").fetchall()
    assert run_pipeline(db, [StaticSource()])["eventsStored"] == 1


def test_failed_real_source_preserves_previous_observation(db):
    run_pipeline(db, [StaticSource()])
    old = snapshot(db)["events"]

    class Failed(StaticSource):
        def collect(self):
            raise httpx.ConnectError("offline")

    report = run_pipeline(db, [Failed()])
    assert report["status"] == "Failed" and report["eventsStored"] == 1
    assert snapshot(db)["events"] == old


def test_contradictory_official_time_and_body_stay_unresolved():
    row = {
        "id": "one",
        "title": "苏州测试演出",
        "attributeMapSingle": {"time": {"value": "2026-10-10 19:30"}},
        "content": "<p>2026.10.17（周六）19:30</p><p>苏州文化艺术中心大剧院</p>",
    }
    event = extract(
        item(json.dumps({"content": [row]}), "orchestra_json").model_copy(
            update={"locator": "one"}
        ),
        "venue",
    )
    assert event["start_date"] is None
    assert event["field_evidence"]["start_date"]["status"] == "Needs Review"
    assert event["field_evidence"]["start_date"]["candidates"] == [
        "2026-10-10",
        "2026-10-17",
    ]


def test_demo_reference_placeholders_and_groups_do_not_leak_into_real_db(db):
    run_pipeline(db, [cls() for cls in DEMO.values()], allow_demo=True)
    run_pipeline(db, [StaticSource()])
    data = snapshot(db)
    assert data["districts"] == []
    assert all("DEMO" not in r["name"] for r in data["venues"] + data["hotels"])
    assert any(r["id"] == "v-expo" for r in data["venues"])
    assert any(r["id"] == "h-inter" for r in data["hotels"])


def test_empty_demo_adapter_cannot_register_a_production_source(db):
    class EmptyDemo(next(iter(DEMO.values()))):
        def collect(self):
            return []

    assert run_pipeline(db, [EmptyDemo()])["status"] == "Failed"
    assert snapshot(db)["status"]["mockSourceCount"] == 0
