"""Importing a hotel's own spreadsheet.

The point of this module is that the customer's file is not in our shape, so the tests use the
headers real exports carry: 出租率, 入住率(%), OCCUPANCY. The rest is about refusing rows with
a reason instead of dropping them.
"""
import pytest

from backend import private_import as imp
from backend import tenants


def csv_bytes(text: str) -> bytes:
    return text.encode("utf-8")


# --- header recognition -----------------------------------------------------------

def test_real_header_spellings_land_on_the_same_metric():
    headers = ["日期", "出租率(%)", "平均房价", "间夜数"]
    mapping = imp.detect_mapping(headers)
    assert mapping["period"] == 0
    assert mapping["occupancy_pct"] == 1
    assert mapping["adr"] == 2
    assert mapping["room_nights"] == 3


def test_english_and_percent_signs_are_understood():
    mapping = imp.detect_mapping(["Date", "OCCUPANCY", "ADR", "Channel"])
    assert mapping["period"] == 0
    assert mapping["occupancy_pct"] == 1
    assert mapping["adr"] == 2
    assert mapping["channel"] == 3


def test_an_unknown_column_is_left_unmapped_rather_than_guessed():
    mapping = imp.detect_mapping(["日期", "入住率", "备注"])
    assert "period" in mapping and "occupancy_pct" in mapping
    assert all(index != 2 for index in mapping.values())


def test_units_and_punctuation_do_not_prevent_a_match():
    assert imp.normalise_header("入住率（%）") == "入住率"
    assert imp.normalise_header("平均房价 (元)") == "平均房价"


# --- numbers and periods ----------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("82.5", 82.5), ("82.5%", 82.5), ("1,234", 1234.0), ("¥620 元", 620.0), ("", None),
])
def test_numbers_survive_the_shapes_exports_use(raw, expected):
    assert imp.parse_number(raw) == expected


@pytest.mark.parametrize("raw,start,end", [
    ("2026-10-01", "2026-10-01", None),
    ("2026/10/01", "2026-10-01", None),
    ("2026.10.01", "2026-10-01", None),
    ("2026年10月1日", "2026-10-01", None),
    ("2026-10-01 至 2026-10-07", "2026-10-01", "2026-10-07"),
    ("2026-10-01~2026-10-07", "2026-10-01", "2026-10-07"),
    ("去年", "", None),
])
def test_periods_survive_the_shapes_exports_use(raw, start, end):
    assert imp.parse_period(raw) == (start, end)


# --- the preview, which is the contract with the customer -------------------------

def test_a_clean_file_previews_as_accepted_rows():
    headers, rows = imp.parse_table(csv_bytes(
        "日期,入住率,平均房价\n2026-10-01,82.5,620\n2026-10-02,78,610\n"))
    mapping = imp.detect_mapping(headers)
    preview = imp.build_preview(headers, rows, mapping)
    assert preview["rows_read"] == 2
    assert len(preview["accepted"]) == 4
    assert preview["issues"] == []


def test_a_bad_percentage_is_reported_with_its_row_not_dropped():
    headers, rows = imp.parse_table(csv_bytes(
        "日期,入住率\n2026-10-01,120\n"))
    preview = imp.build_preview(headers, rows, imp.detect_mapping(headers))
    assert preview["accepted"] == []
    assert preview["issues"][0]["row"] == 2
    assert "0–100" in preview["issues"][0]["reason"]


def test_an_unreadable_date_is_reported_with_its_row():
    headers, rows = imp.parse_table(csv_bytes(
        "日期,入住率\n上周,80\n"))
    preview = imp.build_preview(headers, rows, imp.detect_mapping(headers))
    assert preview["accepted"] == []
    assert "日期无法识别" in preview["issues"][0]["reason"]


def test_a_non_numeric_value_is_reported():
    headers, rows = imp.parse_table(csv_bytes(
        "日期,平均房价\n2026-10-01,待定\n"))
    preview = imp.build_preview(headers, rows, imp.detect_mapping(headers))
    assert preview["issues"][0]["row"] == 2
    assert "不是数字" in preview["issues"][0]["reason"]


def test_a_file_without_a_date_column_is_refused_outright():
    headers, rows = imp.parse_table(csv_bytes("入住率,平均房价\n80,600\n"))
    with pytest.raises(ValueError, match="No date column"):
        imp.build_preview(headers, rows, imp.detect_mapping(headers))


def test_a_file_without_any_metric_column_is_refused_outright():
    headers, rows = imp.parse_table(csv_bytes("日期,备注\n2026-10-01,无\n"))
    with pytest.raises(ValueError, match="No metric column"):
        imp.build_preview(headers, rows, imp.detect_mapping(headers))


def test_channel_and_room_type_travel_with_the_row():
    headers, rows = imp.parse_table(csv_bytes(
        "日期,渠道占比,渠道\n2026-10-01,31.5,携程\n"))
    preview = imp.build_preview(headers, rows, imp.detect_mapping(headers))
    assert preview["accepted"][0]["channel"] == "携程"


def test_an_empty_file_is_refused():
    with pytest.raises(ValueError, match="empty"):
        imp.parse_table(b"", filename="a.csv")


# --- writing it into the tenant's own database ------------------------------------

def test_committing_a_preview_writes_only_into_that_tenants_ledger(tmp_path):
    base = tmp_path / "data"
    base.mkdir()
    headers, rows = imp.parse_table(csv_bytes(
        "日期,入住率\n2026-10-01,82.5\n2026-10-02,78\n"))
    preview = imp.build_preview(headers, rows, imp.detect_mapping(headers))

    con_a = tenants.open_tenant_db(base, "hotel-a")
    written = imp.commit_preview(con_a, preview, uploaded_by="a-manager",
                                source_file="october.xlsx")
    assert written == 2
    a_rows = tenants.read_metrics(con_a, metric="occupancy_pct")
    con_a.close()
    assert [r["value"] for r in a_rows] == [82.5, 78.0]
    assert all(r["uploaded_by"] == "a-manager" for r in a_rows)

    # The other hotel's file does not exist yet, and reading it yields nothing.
    con_b = tenants.open_tenant_db(base, "hotel-b")
    assert tenants.read_metrics(con_b) == []
    con_b.close()


def test_xlsx_without_openpyxl_says_so_instead_of_crashing():
    try:
        import openpyxl  # noqa: F401
        pytest.skip("openpyxl is installed here")
    except ImportError:
        pass
    with pytest.raises(ValueError, match="openpyxl"):
        imp.parse_table(b"PK\x03\x04not really", filename="book.xlsx")
