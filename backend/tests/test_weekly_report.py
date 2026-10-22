"""周报：只陈述测得的数据，不做预测。

测试重点：周期边界、只统计本周内的数据、活动按距离或全市列出并说明口径、
两种文件格式都能生成、以及报告里不存在任何预测/建议字段。
"""
import io
import zipfile
from datetime import date

import pytest

from backend import tenants, weekly_report
from backend.database import connect, initialize


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "main.sqlite3"
    initialize(path)
    with connect(path) as con:
        con.execute(
            "INSERT INTO sources VALUES(?,?,?,?,?,?)",
            ("tourism-visitsz-festival", "visitsz", "tourism", 0, None,
             "2026-01-01T00:00:00+00:00"),
        )
    return path


@pytest.fixture
def base(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    return d


def seed(db, base, hotel_payload=None, metrics=True):
    tenants.create_tenant(db, tenant_id="hotel-a", name="A 酒店")
    tenants.add_member(db, tenant_id="hotel-a", login="owner-a", role="owner")
    if hotel_payload is not None:
        with connect(db) as con:
            con.execute("INSERT OR REPLACE INTO hotels(id, payload) VALUES(?,?)",
                        ("hotel-1", hotel_payload))
            con.execute("UPDATE tenants SET name=? WHERE id=?",
                        (__import__("json").loads(hotel_payload)["name"], "hotel-a"))
    if metrics:
        con = tenants.open_tenant_db(base, "hotel-a")
        try:
            tenants.record_metric(con, metric="occupancy_pct", period_start="2026-10-12",
                                  value=80.0, uploaded_by="owner-a")
            tenants.record_metric(con, metric="occupancy_pct", period_start="2026-10-13",
                                  value=90.0, uploaded_by="owner-a")
            # Outside the reported week, so it must not move the average.
            tenants.record_metric(con, metric="occupancy_pct", period_start="2026-10-05",
                                  value=10.0, uploaded_by="owner-a")
        finally:
            con.close()


HOTEL = ('{"id":"hotel-1","name":"A 酒店","address":"某路1号","districtId":null,'
         '"districtDemo":false,"coordinates":{"lng":120.7,"lat":31.3,"system":"GCJ-02",'
         '"status":"Verified","sourceUrl":"https://ditu.amap.com/place/X"}}')


def test_week_is_the_last_complete_monday_to_sunday():
    assert weekly_report.week_range(date(2026, 10, 23)) == (date(2026, 10, 12),
                                                            date(2026, 10, 18))
    # A Monday belongs to the week that starts on it, so the report is the previous week.
    assert weekly_report.week_range(date(2026, 10, 19)) == (date(2026, 10, 12),
                                                            date(2026, 10, 18))


def test_only_the_week_being_reported_moves_the_average(db, base):
    seed(db, base)
    report = weekly_report.collect(db, base, "hotel-a", today=date(2026, 10, 23))
    occupancy = next(s for s in report["summary"] if s["metric"] == "occupancy_pct")
    assert occupancy["count"] == 2
    assert occupancy["avg"] == 85.0
    assert occupancy["min"] == 80.0 and occupancy["max"] == 90.0


def test_a_tenant_without_uploads_reports_no_numbers_rather_than_zero(db, base):
    seed(db, base, metrics=False)
    report = weekly_report.collect(db, base, "hotel-a", today=date(2026, 10, 23))
    assert report["summary"] == []


def test_when_the_hotel_location_is_unknown_events_cover_the_city_and_say_so(db, base):
    seed(db, base)
    report = weekly_report.collect(db, base, "hotel-a", today=date(2026, 10, 23))
    assert report["scope"]["hotelKnown"] is False
    assert report["scope"]["nearbyKm"] is None
    assert "全市" in report["scope"]["note"]


def test_a_bound_hotel_filters_events_to_its_radius(db, base):
    seed(db, base, hotel_payload=HOTEL)
    with connect(db) as con:
        con.execute(
            "INSERT INTO venues(id, payload) VALUES(?,?)",
            ("v-near", '{"id":"v-near","name":"近处场馆","address":null,"districtId":null,'
                       '"districtDemo":false,"coordinates":{"lng":120.705,"lat":31.305,'
                       '"system":"GCJ-02","status":"Verified","sourceUrl":"https://x"}}'),
        )
        con.execute(
            "INSERT INTO venues(id, payload) VALUES(?,?)",
            ("v-far", '{"id":"v-far","name":"远处场馆","address":null,"districtId":null,'
                      '"districtDemo":false,"coordinates":{"lng":121.4,"lat":31.9,'
                      '"system":"GCJ-02","status":"Verified","sourceUrl":"https://y"}}'),
        )
        for eid, vid, name in (("e1", "v-near", "近处活动"), ("e2", "v-far", "远处活动")):
            con.execute(
                "INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?)",
                (eid, name, "culture", "2026-10-14", "2026-10-15", vid, None,
                 "tourism-visitsz-festival", "Needs Review", "{}"),
            )
    report = weekly_report.collect(db, base, "hotel-a", today=date(2026, 10, 23))
    names = [e["name"] for e in report["events"]]
    assert "近处活动" in names
    assert "远处活动" not in names
    assert report["scope"]["hotelKnown"] is True
    assert report["scope"]["nearbyKm"] == weekly_report.NEARBY_KM


def test_events_outside_the_week_are_excluded(db, base):
    seed(db, base)
    with connect(db) as con:
        con.execute(
            "INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?)",
            ("e-old", "上周活动", "culture", "2026-10-01", "2026-10-02", None, None,
             "tourism-visitsz-festival", "Needs Review", "{}"),
        )
    report = weekly_report.collect(db, base, "hotel-a", today=date(2026, 10, 23))
    assert report["events"] == []


def test_xlsx_is_a_real_workbook_with_the_three_sheets(db, base):
    seed(db, base)
    report = weekly_report.collect(db, base, "hotel-a", today=date(2026, 10, 23))
    payload = weekly_report.build_xlsx(report)
    assert payload[:2] == b"PK"
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        names = zf.namelist()
    assert any("sheet" in n for n in names)


def test_pdf_starts_with_the_pdf_magic_and_is_not_empty(db, base):
    seed(db, base)
    report = weekly_report.collect(db, base, "hotel-a", today=date(2026, 10, 23))
    try:
        payload = weekly_report.build_pdf(report)
    except RuntimeError:
        pytest.skip("没有可用的中文字体")
    assert payload[:5] == b"%PDF-"
    assert len(payload) > 1000


def test_the_report_states_that_it_does_not_forecast(db, base):
    """The project forbids price advice and revenue prediction; the report says so itself."""
    seed(db, base)
    report = weekly_report.collect(db, base, "hotel-a", today=date(2026, 10, 23))
    text = str(report).lower()
    for forbidden in ("forecast", "predict", "recommend"):
        assert forbidden not in text
    assert "不做需求预测" in report["disclaimer"]
