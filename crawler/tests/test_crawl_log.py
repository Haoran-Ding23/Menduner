"""Per-source crawl history and consecutive-failure alerts.

The reported complaint was that a failing source was invisible: the job report said "Failed" and
nothing recorded it, so nobody could tell whether a source had been broken for one run or for
three weeks. These tests pin the behaviour that makes that answerable:

  * every source of every run leaves a row, success or failure;
  * one failure is a blip, ``ALERT_THRESHOLD`` in a row raises exactly one alert;
  * a success resolves the open alert instead of leaving it set forever;
  * the crawl log can never abort a crawl — it is diagnostics, not a dependency.
"""
from __future__ import annotations

import json

from backend.database import connect, initialize
from crawler import crawl_log


def report(attempts: list[dict]) -> dict:
    return {"jobId": "job-1", "attempts": attempts}


def attempt(source: str, status: str, accepted: int = 0, error: str | None = None) -> dict:
    return {
        "source": source,
        "status": status,
        "accepted": accepted,
        "rejected": 0,
        "error": error,
        "pagesCollected": 1,
    }


def run(con, attempts, when="2026-10-14T08:00:00+00:00") -> dict:
    return crawl_log.record_run(
        con, report=report(attempts), started_at=when, finished_at=when
    )


def test_every_source_of_every_run_is_recorded(tmp_path):
    db = tmp_path / "log.sqlite3"
    initialize(db)
    with connect(db) as con:
        run(con, [attempt("a", "Success", accepted=3), attempt("b", "Failed", error="boom")])
        run(con, [attempt("a", "Partial", accepted=1), attempt("b", "Failed", error="boom")])
        rows = crawl_log.recent_runs(con, limit=10)
    assert len(rows) == 4
    by_source = [(r["source_id"], r["status"]) for r in rows]
    assert ("a", "SUCCESS") in by_source and ("a", "PARTIAL") in by_source
    assert by_source.count(("b", "FAILED")) == 2
    assert rows[0]["job_id"] == "job-1"


def test_a_failure_reason_is_stored_readably(tmp_path):
    db = tmp_path / "log.sqlite3"
    initialize(db)
    # The pipeline sometimes reports a JSON blob of per-URL errors; the stored reason must be a
    # readable sentence, not the raw blob.
    blob = json.dumps(
        [{"error": "robots.txt disallows this URL; no public page request made", "url": "x"}]
    )
    with connect(db) as con:
        run(con, [attempt("damai", "Failed", error=blob)])
        row = crawl_log.recent_runs(con, limit=1)[0]
    assert row["failure_reason"] == "robots.txt disallows this URL; no public page request made"


def test_three_consecutive_failures_raise_one_alert(tmp_path):
    db = tmp_path / "log.sqlite3"
    initialize(db)
    with connect(db) as con:
        first = run(con, [attempt("broken", "Failed", error="e1")])
        second = run(con, [attempt("broken", "Failed", error="e2")])
        third = run(con, [attempt("broken", "Failed", error="e3")])
        fourth = run(con, [attempt("broken", "Failed", error="e4")])

    assert first["raised"] == [], "one failure is a blip, not an alert"
    assert second["raised"] == [], "two failures is still not an alert"
    assert len(third["raised"]) == 1, f"expected an alert at {crawl_log.ALERT_THRESHOLD}"
    assert third["raised"][0]["consecutive_failures"] == 3
    assert third["raised"][0]["reason"] == "e3"

    with connect(db) as con:
        alerts = crawl_log.open_alerts(con)
    assert len(alerts) == 1, "a source broken for a month must not add 30 rows"
    assert alerts[0]["consecutive_failures"] == 4, "the open alert tracks the latest count"


def test_a_success_resolves_the_open_alert(tmp_path):
    db = tmp_path / "log.sqlite3"
    initialize(db)
    with connect(db) as con:
        for _ in range(3):
            run(con, [attempt("flaky", "Failed", error="down")])
        assert len(crawl_log.open_alerts(con)) == 1
        result = run(con, [attempt("flaky", "Success", accepted=2)])
        assert len(result["resolved"]) == 1
        assert crawl_log.open_alerts(con) == []


def test_an_interrupted_failure_streak_does_not_alert(tmp_path):
    """A source that fails, works, then fails again is unreliable, not broken."""
    db = tmp_path / "log.sqlite3"
    initialize(db)
    with connect(db) as con:
        run(con, [attempt("flappy", "Failed")])
        run(con, [attempt("flappy", "Failed")])
        run(con, [attempt("flappy", "Success", accepted=1)])
        result = run(con, [attempt("flappy", "Failed")])
        assert result["raised"] == []
        assert crawl_log.open_alerts(con) == []


def test_health_reports_the_last_run_and_failure_reason(tmp_path):
    db = tmp_path / "log.sqlite3"
    initialize(db)
    with connect(db) as con:
        run(con, [attempt("good", "Success", accepted=5)])
        run(con, [attempt("bad", "Failed", error="certificate not valid")])
        health = {row["source_id"]: row for row in crawl_log.source_health(con)}
    assert health["good"]["last_status"] == "SUCCESS"
    assert health["good"]["last_events_found"] == 5
    assert health["bad"]["last_status"] == "FAILED"
    assert health["bad"]["last_failure_reason"] == "certificate not valid"
    assert health["bad"]["consecutive_failures"] == 1


def test_logging_never_aborts_a_crawl(tmp_path):
    """Missing tables or an unregistered source must not raise: the log is diagnostics."""
    db = tmp_path / "bare.sqlite3"
    with connect(db) as con:
        # No initialize(): crawl_runs/crawl_alerts and sources may not exist yet.
        result = crawl_log.record_run(
            con,
            report=report([attempt("never-registered", "Failed", error="x")]),
            started_at="2026-10-14T08:00:00+00:00",
            finished_at="2026-10-14T08:00:00+00:00",
        )
    assert result["raised"] == []
