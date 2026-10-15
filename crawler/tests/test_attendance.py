"""Attendance records.

This table exists to accumulate a dataset, so its value depends on what it refuses. A bad row
becomes a bad training example later and nothing downstream can tell, which is why most of
these tests are about rejection rather than storage.
"""
from datetime import datetime, timezone

import pytest

from backend.database import connect, initialize
from crawler import attendance


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "attendance.sqlite3"
    initialize(path)
    with connect(path) as con:
        con.execute(
            "INSERT INTO sources VALUES(?,?,?,?,?,?)",
            ("tourism-visitsz-festival", "test", "tourism", 0, None,
             "2026-01-01T00:00:00+00:00"),
        )
        con.execute(
            "INSERT INTO venues(id,payload) VALUES(?,?)",
            ("v1", '{"id":"v1","name":"苏州文化艺术中心·金鸡湖音乐厅","address":"观枫街1号",'
                   '"districtId":null,"districtDemo":false,"coordinates":null}'),
        )
        con.execute(
            "INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?)",
            ("evt-1", "测试活动", "culture", "2026-11-01", "2026-11-02", "v1", None,
             "tourism-visitsz-festival", "Needs Review", "{}"),
        )
        attendance.ensure_schema(con)
    return path


def ok(con, **over):
    """A valid record linked to the fixture event, with fields overridden per test."""
    base = dict(
        event_id="evt-1",
        subject_name="测试活动",
        observed_on="2026-11-01",
        count=5000,
        measure="single_day",
        method="official",
        source_type="official_site",
        collected_by="组员A",
        source_url="https://example.invalid/notice",
    )
    base.update(over)
    return attendance.record(con, **base)


# --- the four design decisions -------------------------------------------------

def test_many_measurements_of_one_event_are_all_kept(db):
    """Disagreement between sources is information, so it is never collapsed."""
    with connect(db) as con:
        attendance.ensure_schema(con)
        ok(con, count=5000, method="official", measure="tickets_sold",
           source_url="https://example.invalid/a")
        ok(con, count=3000, method="news", measure="single_day",
           source_url="https://example.invalid/b")
        ok(con, count=800, method="inference", measure="rooms_booked", confidence="low",
           source_url="https://example.invalid/c")
        rows = attendance.for_event(con, "evt-1")
    assert len(rows) == 3
    assert sorted(r["count"] for r in rows) == [800, 3000, 5000]


def test_a_measurement_can_be_recorded_for_an_event_we_never_crawled(db):
    """Otherwise the dataset could only ever cover our own events, which is the biased set.

    The project holds upcoming events, so historical attendance - the part a model most needs
    - belongs to events outside the table entirely.
    """
    with connect(db) as con:
        attendance.ensure_schema(con)
        result = attendance.record(
            con,
            subject_name="2019 苏州某音乐节",   # never in our events table
            observed_on="2019-10-05",
            count=12000,
            measure="full_run",
            method="news",
            source_type="news_media",
            collected_by="组员B",
            source_url="https://example.invalid/2019",
        )
    assert result["count"] == 12000
    with connect(db) as con:
        assert attendance.for_event(con, "evt-1") == []


def test_an_unknown_event_id_is_refused_rather_than_silently_unlinked(db):
    with connect(db) as con:
        attendance.ensure_schema(con)
        with pytest.raises(ValueError, match="Unknown event"):
            ok(con, event_id="evt-does-not-exist")


def test_the_measure_is_required_because_scopes_are_not_comparable(db):
    with connect(db) as con:
        attendance.ensure_schema(con)
        with pytest.raises(ValueError, match="measure must be one of"):
            ok(con, measure="people")
        with pytest.raises(ValueError, match="measure must be one of"):
            ok(con, measure=None)


def test_the_method_is_required_so_an_estimate_is_never_read_as_a_measurement(db):
    with connect(db) as con:
        attendance.ensure_schema(con)
        with pytest.raises(ValueError, match="method must be one of"):
            ok(con, method="looked about right")


# --- attribution, the project's standing rule ----------------------------------

def test_a_number_with_no_source_and_no_named_source_is_refused(db):
    """An unattributable number cannot be traced, and this project does not store those."""
    with connect(db) as con:
        attendance.ensure_schema(con)
        with pytest.raises(ValueError, match="source URL or a named source"):
            ok(con, source_url=None, source_name=None)
        with pytest.raises(ValueError, match="source URL or a named source"):
            ok(con, source_url="   ", source_name="  ")


def test_a_named_source_is_enough_when_there_is_no_page(db):
    """A figure from a venue's own staff is legitimate; it just has to name who said it."""
    with connect(db) as con:
        attendance.ensure_schema(con)
        result = ok(con, source_url=None, source_name="某酒店店长",
                    source_type="venue_staff", method="field_observation")
    assert result["id"].startswith("att:")


def test_a_collector_must_be_named(db):
    with connect(db) as con:
        attendance.ensure_schema(con)
        with pytest.raises(ValueError, match="who collected it"):
            ok(con, collected_by="   ")


def test_a_non_http_source_url_is_refused(db):
    with connect(db) as con:
        attendance.ensure_schema(con)
        with pytest.raises(ValueError, match="http"):
            ok(con, source_url="example.invalid/notice")


# --- rejection of numbers that would poison a dataset ---------------------------

def test_an_estimate_may_not_be_recorded_as_high_confidence(db):
    """A capacity-derived figure is an estimate of attendance, not a measurement of it."""
    with connect(db) as con:
        attendance.ensure_schema(con)
        with pytest.raises(ValueError, match="cannot be recorded as high confidence"):
            ok(con, method="capacity_estimate", confidence="high")
        with pytest.raises(ValueError, match="cannot be recorded as high confidence"):
            ok(con, method="inference", confidence="high")
        # The same figure is fine once it is labelled as what it is.
        assert ok(con, method="capacity_estimate", confidence="low")["method"] == "capacity_estimate"


def test_a_negative_or_fractional_count_is_refused(db):
    with connect(db) as con:
        attendance.ensure_schema(con)
        with pytest.raises(ValueError, match="non-negative whole number"):
            ok(con, count=-1)
        with pytest.raises(ValueError, match="non-negative whole number"):
            ok(con, count=500.5)
        with pytest.raises(ValueError, match="non-negative whole number"):
            ok(con, count=True)


def test_an_impossible_date_is_refused(db):
    with connect(db) as con:
        attendance.ensure_schema(con)
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            ok(con, observed_on="2026-13-45")
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            ok(con, observed_on="去年十一月")


def test_a_nonsense_capacity_is_refused(db):
    with connect(db) as con:
        attendance.ensure_schema(con)
        with pytest.raises(ValueError, match="positive"):
            ok(con, venue_capacity=0)
        with pytest.raises(ValueError, match="whole number"):
            ok(con, venue_capacity="1200")


def test_the_same_measurement_twice_is_refused_but_a_different_one_is_not(db):
    with connect(db) as con:
        attendance.ensure_schema(con)
        ok(con)
        with pytest.raises(ValueError, match="already recorded"):
            ok(con)
        # A different count is a different measurement and must go in.
        assert ok(con, count=5100)["count"] == 5100


def test_a_missing_subject_name_is_refused(db):
    with connect(db) as con:
        attendance.ensure_schema(con)
        with pytest.raises(ValueError, match="event's name"):
            ok(con, subject_name="  ")


# --- what the dataset can say about itself -------------------------------------

def test_summary_reports_an_empty_dataset_as_empty_not_as_zero_coverage(db):
    with connect(db) as con:
        attendance.ensure_schema(con)
        state = attendance.summary(con)
    assert state["total"] == 0
    assert state["status"] == "empty"
    assert state["first_observed_on"] is None


def test_summary_separates_estimates_from_measurements(db):
    with connect(db) as con:
        attendance.ensure_schema(con)
        ok(con, method="official")
        ok(con, count=100, method="capacity_estimate", confidence="low",
           observed_on="2026-11-02")
        ok(con, count=200, method="inference", confidence="low",
           observed_on="2026-11-03")
        state = attendance.summary(con)
    assert state["total"] == 3
    assert state["estimated"] == 2
    assert state["status"] == "collecting"
    assert state["first_observed_on"] == "2026-11-01"
    assert state["last_observed_on"] == "2026-11-03"


def test_summary_counts_unlinked_history_separately(db):
    """Unlinked rows are the historical measurements, and their size matters to a reader."""
    with connect(db) as con:
        attendance.ensure_schema(con)
        ok(con, event_id="evt-1")
        attendance.record(con, subject_name="2019 音乐节", observed_on="2019-10-05",
                          count=12000, measure="full_run", method="news",
                          source_type="news_media", collected_by="组员B",
                          source_url="https://example.invalid/2019")
        state = attendance.summary(con)
    assert state["linked_to_event"] == 1
    assert state["unlinked"] == 1


def test_the_dataset_start_date_is_recorded(db):
    """So a later reader can tell how long collection has been running."""
    assert attendance.dataset_start() == "2026-10-15"


# --- the training export --------------------------------------------------------

def test_export_computes_utilisation_only_when_both_halves_exist(db):
    with connect(db) as con:
        attendance.ensure_schema(con)
        ok(con, event_id="evt-1", count=600, venue_capacity=1200)
        ok(con, count=300, measure="peak_day", event_id=None,
           observed_on="2026-11-02", source_url="https://example.invalid/d")
        rows = attendance.export_training_rows(con)
    with_capacity = next(r for r in rows if r["count"] == 600)
    without = next(r for r in rows if r["count"] == 300)
    assert with_capacity["utilisation"] == 0.5
    assert without["utilisation"] is None


def test_export_carries_the_event_and_venue_context_when_linked(db):
    with connect(db) as con:
        attendance.ensure_schema(con)
        ok(con, event_id="evt-1")
        rows = attendance.export_training_rows(con)
    assert rows[0]["event_name"] == "测试活动"
    assert rows[0]["event_category"] == "culture"
    assert rows[0]["venue_name"] == "苏州文化艺术中心·金鸡湖音乐厅"


def test_export_keeps_estimates_by_default_and_drops_them_on_request(db):
    with connect(db) as con:
        attendance.ensure_schema(con)
        ok(con, method="official")
        ok(con, count=100, method="capacity_estimate", confidence="low",
           observed_on="2026-11-02")
        everything = attendance.export_training_rows(con)
        measured = attendance.export_training_rows(con, measured_only=True)
    assert len(everything) == 2
    assert len(measured) == 1
    assert measured[0]["method"] == "official"


def test_export_never_returns_a_model_output_or_a_price(db):
    """The table stores observations; nothing derived from them is written back here."""
    with connect(db) as con:
        attendance.ensure_schema(con)
        ok(con)
        row = attendance.export_training_rows(con)[0]
    for forbidden in ("price", "revenue", "prediction", "forecast", "recommended"):
        assert not any(forbidden in key for key in row), forbidden


def test_the_table_has_no_column_that_could_hold_a_price_or_a_prediction(db):
    with connect(db) as con:
        attendance.ensure_schema(con)
        columns = {r[1] for r in con.execute("PRAGMA table_info(attendance_records)")}
    assert columns == {
        "id", "event_id", "subject_name", "observed_on", "measure", "count", "method",
        "confidence", "source_type", "source_name", "source_url", "source_text",
        "venue_capacity", "collected_by", "collected_at", "note",
    }
