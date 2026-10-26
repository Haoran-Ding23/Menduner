"""城市活动周报（§3 Excel MVP）的测试。

对应 GPT Round 2 给出的 8 项验收清单：
  1. 五张工作表结构与数据
  2. 城市/区县层级不重复计数
  3. 跨月、跨年、多日与日期边界
  4. 无历史快照时不生成虚假变化
  5. 危险文本保存后重新加载不是公式类型
  6. 鉴权（由路由测试覆盖，见 test_city_report_route）
  7. 空结果、非法地区、过大区间有确定行为
  8. 只读、不触碰原有数据
"""
import io
import json

import pytest
from openpyxl import load_workbook

from backend import city_report, geo
from backend.database import connect, initialize


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "main.sqlite3"
    initialize(path)
    with connect(path) as con:
        con.execute("INSERT INTO sources VALUES(?,?,?,?,?,?)",
                    ("s1", "官方来源", "government", 0, "https://a.test/x", "2026-10-01T00:00:00+00:00"))
        districts = [
            {"id": "suzhou", "name": "苏州市", "kind": "city", "parentId": None},
            {"id": "taicang", "name": "太仓市", "kind": "county_city", "parentId": "suzhou"},
            {"id": "gusu", "name": "姑苏区", "kind": "district", "parentId": "suzhou"},
            {"id": "district-太仓", "name": "太仓老城", "kind": "business_area", "parentId": "taicang"},
        ]
        for district in districts:
            con.execute("INSERT INTO districts(id,payload) VALUES(?,?)",
                        (district["id"], json.dumps(district, ensure_ascii=False)))
        con.execute("INSERT INTO venues(id,payload) VALUES(?,?)",
                    ("v-ok", json.dumps({"id": "v-ok", "name": "太仓大剧院",
                                         "coordinates": {"lng": 121.1, "lat": 31.4}})))
        con.execute("INSERT INTO venues(id,payload) VALUES(?,?)",
                    ("v-nocoord", json.dumps({"id": "v-nocoord", "name": "无坐标场馆"})))
    with connect(path) as con:
        try:
            con.execute("ALTER TABLE events ADD COLUMN canonical_id TEXT")
        except Exception:
            pass
    return path


def add_event(db, event_id, name, start, end=None, venue="v-ok", district="taicang",
              canonical=None, status="Needs Review", source="s1"):
    with connect(db) as con:
        con.execute(
            "INSERT INTO events(id,name,category,startDate,endDate,venue,district,source,"
            "verification_status,payload,canonical_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (event_id, name, "culture", start, end, venue, district, source, status, "{}",
             canonical or event_id),
        )


def xlsx(report):
    return load_workbook(io.BytesIO(city_report.build_xlsx(report)))


def test_five_sheets_and_overview_counts(db):
    add_event(db, "e1", "活动一", "2026-10-20", "2026-10-22")
    add_event(db, "e2", "活动二", "2026-10-21")
    report = city_report.collect(db, "taicang", "2026-10-19", "2026-10-25")
    book = xlsx(report)
    assert book.sheetnames == ["城市概览", "活动明细", "本期变化", "来源证据", "待确认事项"]
    assert report["meta"]["uniqueActivities"] == 2
    # 覆盖天数：20-22 三天 + 21 一天（21 已被计入）= 4
    assert report["meta"]["activityDays"] == 4
    assert book["活动明细"].max_row == 3  # 表头 + 2 行
    assert book["活动明细"].max_column == 10  # 不再包含内部规范化身份列


def test_city_scope_does_not_double_count(db):
    add_event(db, "e1", "太仓活动", "2026-10-20", district="taicang")
    add_event(db, "e2", "姑苏活动", "2026-10-20", district="gusu")
    # 同一个身份出现在两个地区：仍只算一次
    add_event(db, "e3", "跨源活动", "2026-10-20", district="taicang", canonical="e3")
    add_event(db, "e3b", "跨源活动", "2026-10-20", district="taicang", canonical="e3")

    city = city_report.collect(db, "suzhou", "2026-10-19", "2026-10-25")
    assert city["meta"]["uniqueActivities"] == 3
    taicang = city_report.collect(db, "taicang", "2026-10-19", "2026-10-25")
    assert taicang["meta"]["uniqueActivities"] == 2  # e1 + e3（去重后）
    gusu = city_report.collect(db, "gusu", "2026-10-19", "2026-10-25")
    assert gusu["meta"]["uniqueActivities"] == 1


def test_scope_includes_child_business_area(db):
    add_event(db, "e1", "商圈活动", "2026-10-20", district="district-太仓")
    report = city_report.collect(db, "taicang", "2026-10-19", "2026-10-25")
    assert report["meta"]["uniqueActivities"] == 1
    assert report["meta"]["scopeSize"] == 2  # taicang + 子级商圈


def test_cross_year_activity_appears_in_both_windows_but_counts_once(db):
    add_event(db, "e1", "跨年展", "2026-12-30", "2027-01-03")
    first = city_report.collect(db, "taicang", "2026-12-28", "2026-12-31")
    second = city_report.collect(db, "taicang", "2027-01-01", "2027-01-05")
    assert first["meta"]["uniqueActivities"] == 1
    assert second["meta"]["uniqueActivities"] == 1
    # 各区间内只算一个活动，不是按天复制
    assert len(first["detail"]) == 1
    assert first["detail"][0]["daysCovered"] == 2   # 12-30, 12-31
    assert second["detail"][0]["daysCovered"] == 3  # 01-01..01-03


def test_multi_day_activity_not_expanded_into_rows(db):
    add_event(db, "e1", "长展", "2026-10-01", "2026-10-31")
    report = city_report.collect(db, "taicang", "2026-10-19", "2026-10-25")
    assert len(report["detail"]) == 1
    assert report["detail"][0]["daysCovered"] == 7


def test_no_snapshot_marks_changes_unavailable(db):
    add_event(db, "e1", "活动", "2026-10-20")
    report = city_report.collect(db, "taicang", "2026-10-19", "2026-10-25")
    assert report["changes"]["available"] is False
    assert "缺少可比历史数据" in report["changes"]["reason"]
    sheet = xlsx(report)["本期变化"]
    text = " ".join(str(cell.value) for row in sheet.iter_rows() for cell in row if cell.value)
    assert "不可用" in text and "缺少可比历史数据" in text


def test_dangerous_text_is_not_a_formula_after_reload(db):
    add_event(db, "e1", '=1+1 危险名称', "2026-10-20")
    add_event(db, "e2", "   @SUM(A1)", "2026-10-20")
    add_event(db, "e3", "-2+3", "2026-10-20")
    report = city_report.collect(db, "taicang", "2026-10-19", "2026-10-25")
    book = xlsx(report)
    sheet = book["活动明细"]
    names = [sheet.cell(row=index, column=1) for index in range(2, sheet.max_row + 1)]
    assert names, "应该有明细行"
    for cell in names:
        # 关键：保存后重新打开时不能是公式类型
        assert cell.data_type != "f", f"单元格被当成公式：{cell.value!r}"
        assert cell.value.startswith("'"), f"危险前缀未转义：{cell.value!r}"


def test_source_url_written_as_plain_text(db):
    add_event(db, "e1", "活动", "2026-10-20")
    report = city_report.collect(db, "taicang", "2026-10-19", "2026-10-25")
    sheet = xlsx(report)["来源证据"]
    url_cell = sheet.cell(row=2, column=3)
    assert url_cell.value == "https://a.test/x"
    assert url_cell.data_type != "f"
    assert url_cell.hyperlink is None


def test_pending_items_flag_missing_coordinates(db):
    add_event(db, "e1", "无坐标活动", "2026-10-20", venue="v-nocoord")
    report = city_report.collect(db, "taicang", "2026-10-19", "2026-10-25")
    reasons = " ".join(item["reason"] for item in report["pending"])
    assert "坐标" in reasons


def test_empty_result_is_explicit(db):
    report = city_report.collect(db, "taicang", "2026-10-19", "2026-10-25")
    assert report["meta"]["uniqueActivities"] == 0
    book = xlsx(report)
    assert book["活动明细"].max_row == 1  # 只有表头
    assert book["待确认事项"].cell(row=2, column=1).value == "无"


def test_unknown_district_is_rejected(db):
    with pytest.raises(city_report.ReportError, match="地区不存在"):
        city_report.collect(db, "no-such-district", "2026-10-19", "2026-10-25")


def test_oversized_range_is_rejected(db):
    with pytest.raises(city_report.ReportError, match="区间过长"):
        city_report.collect(db, "taicang", "2025-01-01", "2026-12-31")


def test_invalid_dates_are_rejected(db):
    with pytest.raises(city_report.ReportError, match="合法日期"):
        city_report.collect(db, "taicang", "2026-13-01", "2026-13-05")
    with pytest.raises(city_report.ReportError, match="不能晚于"):
        city_report.collect(db, "taicang", "2026-10-25", "2026-10-19")


def test_export_is_read_only(db):
    add_event(db, "e1", "活动", "2026-10-20")
    with connect(db) as con:
        before = con.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        payload_before = con.execute("SELECT payload FROM events WHERE id='e1'").fetchone()[0]
    city_report.build_xlsx(city_report.collect(db, "taicang", "2026-10-19", "2026-10-25"))
    with connect(db) as con:
        after = con.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        payload_after = con.execute("SELECT payload FROM events WHERE id='e1'").fetchone()[0]
    assert before == after
    assert payload_before == payload_after


def test_overview_carries_batch_and_data_through(db):
    add_event(db, "e1", "活动", "2026-10-20")
    report = city_report.collect(db, "taicang", "2026-10-19", "2026-10-25")
    assert report["meta"]["batch"]
    assert report["meta"]["dataThrough"] == "2026-10-20"
    sheet = xlsx(report)["城市概览"]
    text = " ".join(str(cell.value) for row in sheet.iter_rows() for cell in row if cell.value)
    assert "数据批次" in text and "北京" in text


def test_changes_do_not_leak_past_the_window_end(db):
    """GPT Round 3 指出的真实缺陷：历史区间不得混入截止日之后的变化。

    场景：10-19 与 10-21 各一份快照，10-24 才出现「取消」。导出 10-19..10-21 时，
    差分只能基于 19→21，不能把 24 的变化算进来。
    """
    from backend import tracking

    add_event(db, "stay", "保留的活动", "2026-10-25")
    add_event(db, "gone", "后来消失的活动", "2026-10-26")
    tracking.capture(db, "2026-10-19")

    # 10-21：两者都在，没有变化
    tracking.capture(db, "2026-10-21")

    # 10-24（窗口之外）：删掉一条
    with connect(db) as con:
        con.execute("DELETE FROM events WHERE id='gone'")
    tracking.capture(db, "2026-10-24")

    report = city_report.collect(db, "taicang", "2026-10-19", "2026-10-21")
    assert report["changes"]["available"] is True
    # 比较终点必须是 10-21，而不是最新的 10-24
    assert report["changes"]["coverage"]["to"] == "2026-10-21"
    assert report["changes"]["rows"] == []


def test_changes_only_count_the_target_city(db):
    """别的城市的活动消失，不能记成目标城市的「消失」。"""
    from backend import tracking

    add_event(db, "taicang-1", "太仓活动", "2026-10-25", district="taicang")
    add_event(db, "gusu-1", "姑苏活动", "2026-10-25", district="gusu")
    tracking.capture(db, "2026-10-19")

    with connect(db) as con:
        con.execute("DELETE FROM events WHERE id='gusu-1'")
    tracking.capture(db, "2026-10-20")

    report = city_report.collect(db, "taicang", "2026-10-19", "2026-10-20")
    assert report["changes"]["available"] is True
    names = [row["name"] for row in report["changes"]["rows"]]
    assert "姑苏活动" not in names


def test_export_contains_no_private_or_internal_fields(db):
    """公开周报不得出现酒店经营、租户或内部核验字段。"""
    add_event(db, "e1", "公开活动", "2026-10-20")
    book = xlsx(city_report.collect(db, "taicang", "2026-10-19", "2026-10-25"))
    text = " ".join(
        str(cell.value)
        for name in book.sheetnames
        for row in book[name].iter_rows()
        for cell in row
        if cell.value
    )
    for forbidden in ("tenant", "canonical_id", "entityId", "Needs Review", "密码", "经营数据明细"):
        assert forbidden not in text, forbidden
