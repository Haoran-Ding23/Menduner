"""太仓市文体广电和旅游局「太仓文化」栏目的展讯提取。

这个源是「太仓没有活动」这个判断的反例：县市自己的门户网站确实按日期发布展览，
只是入口藏在「政务服务 > 专题服务 > 文化教育」下面，列表路径也无法从文章 URL 猜出来。

这些测试lock住三件事：三种日期写法都要能解析（否则三分之一的展讯会静默消失）、
场馆名不能带上展厅/楼层、没有日期的展讯要拒绝而不是发布成无日期活动。
"""
import pytest

from crawler.extractor import taicang_culture
from crawler.schema import CollectedItem


def item(body_html: str, *, h1: str = "展讯丨测试展览",
         published: str = "2026-10-21 13:39") -> CollectedItem:
    html = f"""<html><body>
    <div class="article">
      <h1>{h1}</h1>
      <div class="article_attr"><span class="date">时间： <b>{published}</b></span>
        <span>来源： <b>太仓市文体广旅局</b></span></div>
      <div id="zoomcon">{body_html}</div>
    </div></body></html>"""
    return CollectedItem(
        item_key="https://www.taicang.gov.cn/taicang/tcwh/202610/test.shtml",
        original_url="https://www.taicang.gov.cn/taicang/tcwh/202610/test.shtml",
        source_name="太仓市文体广电和旅游局·太仓文化栏目",
        crawl_time="2026-10-22T00:00:00+00:00",
        raw_content=html.encode("utf-8"),
        mock=False,
        extractor="taicang_culture",
        is_event=True,
        locator=None,
        request_metadata={},
    )


# --- the three date spellings in the live archive -----------------------------

def test_dotted_range_borrows_the_single_stated_year():
    event = taicang_culture(item("<p>展览日期： 2026.10.20 — 11.20</p>"))
    assert event["start_date"] == "2026-10-20"
    assert event["end_date"] == "2026-11-20"


def test_chinese_spaced_range_parses():
    event = taicang_culture(item("<p>展览日期： 2026 年 9 月 30 日 —11 月 22 日</p>"))
    assert event["start_date"] == "2026-09-30"
    assert event["end_date"] == "2026-11-22"


def test_explicit_end_year_is_kept():
    event = taicang_culture(item("<p>展览时间： 2026.12.20 — 2027.01.15</p>"))
    assert event["start_date"] == "2026-12-20"
    assert event["end_date"] == "2027-01-15"


def test_a_range_that_wraps_the_new_year_gets_the_later_year():
    """2026.12.20 — 1.15 crosses into the next year; recording 2026-01-15 would end before it starts."""
    event = taicang_culture(item("<p>展览日期： 2026.12.20 — 1.15</p>"))
    assert event["start_date"] == "2026-12-20"
    assert event["end_date"] == "2027-01-15"


def test_a_yearless_range_uses_the_publication_year_and_says_so():
    event = taicang_culture(item("<p>展览日期： 8 月 22 日至 9 月 20 日</p>",
                                 published="2026-08-21 10:00"))
    assert event["start_date"] == "2026-08-22"
    assert event["end_date"] == "2026-09-20"
    # The reader must be able to tell this year was derived rather than stated.
    assert "publication year" in event["field_evidence"]["start_date"]["method"]


def test_a_yearless_range_with_no_publication_year_is_refused():
    with pytest.raises(ValueError, match="did not yield a date range"):
        taicang_culture(item("<p>展览日期： 8 月 22 日至 9 月 20 日</p>", published="无"))


def test_digits_split_by_spaces_are_rejoined_before_parsing():
    """The CMS spaces digits out: "1 月 1 5 日" is 1月15日, and it hid a fifth of the archive."""
    event = taicang_culture(item("<p>展览日期： 1 月 1 5 日 - 4 月 1 5 日</p>",
                                 published="2026-01-10 09:00"))
    assert event["start_date"] == "2026-01-15"
    assert event["end_date"] == "2026-04-15"


def test_a_notice_that_writes_hao_instead_of_ri_parses():
    event = taicang_culture(item("<p>展览日期： 2024年9月6号-11月6号</p>"))
    assert event["start_date"] == "2024-09-06"
    assert event["end_date"] == "2024-11-06"


def test_a_notice_without_a_date_line_is_refused_not_published_undated():
    with pytest.raises(ValueError, match="No exhibition date line"):
        taicang_culture(item("<p>展览地点：太仓美术馆</p>"))


# --- the venue is the place, not the room ------------------------------------

def test_room_number_and_hall_are_stripped_from_the_venue_name():
    event = taicang_culture(
        item("<p>展览日期： 2026.10.20 — 11.20 展览地点：太仓美术馆 4 号展厅</p>"))
    assert event["venue"] == "太仓美术馆"
    # The full wording stays available as the location claim.
    assert "4 号展厅" in event["location"]


def test_a_chinese_numeral_floor_is_stripped_too():
    """太仓市博物馆一楼 1 号临展厅 left the venue named 太仓市博物馆一 when the numeral was missed."""
    event = taicang_culture(
        item("<p>展览日期： 2026.09.25 至 12 月 13 日 展览地点：太仓市博物馆一楼 1 号临展厅</p>"))
    assert event["venue"] == "太仓市博物馆"


def test_an_address_in_parentheses_is_not_part_of_the_venue_name():
    event = taicang_culture(
        item("<p>展览日期： 2026.09.24 — 11.09 展览地点：太仓名人馆(太仓市太平南路 38 号)</p>"))
    assert event["venue"] == "太仓名人馆"


def test_the_venue_field_stops_at_the_next_label():
    """The notice puts several labelled fields in one paragraph; the venue must not swallow them."""
    event = taicang_culture(
        item("<p>展览地点：太仓美术馆 简介：本次展览以书法回望长征。</p>"
             "<p>展览日期： 2026.10.20 — 11.20</p>"))
    assert event["venue"] == "太仓美术馆"


def test_a_room_number_list_before_the_room_word_is_stripped_too():
    """太仓美术馆 3 、 4 号展厅 left the venue named 太仓美术馆 3 、 when only the room word matched."""
    event = taicang_culture(
        item("<p>展览日期： 2026.10.20 — 11.20 展览地点：太仓美术馆 3 、 4 号展厅</p>"))
    assert event["venue"] == "太仓美术馆"


def test_a_venue_with_a_trailing_number_and_separator_is_cleaned():
    event = taicang_culture(
        item("<p>展览日期： 2026.10.20 — 11.20 展览地点：太仓美术馆1、 展厅</p>"))
    assert event["venue"] == "太仓美术馆"


def test_a_notice_without_a_venue_still_yields_its_dates():
    event = taicang_culture(item("<p>展览日期： 2026.10.20 — 11.20</p>"))
    assert event["start_date"] == "2026-10-20"
    assert event["venue"] is None


# --- title and attribution ----------------------------------------------------

def test_the_section_prefix_is_removed_from_the_event_name():
    event = taicang_culture(item("<p>展览日期： 2026.10.20 — 11.20</p>",
                                 h1="展讯丨从太仓走来——本土艺术家作品风采展"))
    assert event["event_name"] == "从太仓走来——本土艺术家作品风采展"


def test_the_organiser_is_taken_from_the_labelled_line_only():
    event = taicang_culture(
        item("<p>主办单位：太仓美术馆 支持单位：太仓市美术家协会 展览日期： 2026.10.20 — 11.20</p>"))
    assert event["organizer"] == "太仓美术馆"


def test_every_claim_stays_needs_review_until_a_person_confirms_it():
    event = taicang_culture(item("<p>主办单位：太仓美术馆 展览日期： 2026.10.20 — 11.20 "
                                 "展览地点：太仓美术馆 4 号展厅</p>"))
    assert event["field_evidence"]["start_date"]["status"] == "Needs Review"
    assert event["field_evidence"]["venue"]["status"] == "Needs Review"


def test_missing_selectors_are_refused_rather_than_invented():
    bad = CollectedItem(
        item_key="https://www.taicang.gov.cn/taicang/tcwh/202610/x.shtml",
        original_url="https://www.taicang.gov.cn/taicang/tcwh/202610/x.shtml",
        source_name="太仓文化", crawl_time="2026-10-22T00:00:00+00:00",
        raw_content=b"<html><body>no article here</body></html>",
        mock=False, extractor="taicang_culture", is_event=True,
        locator=None, request_metadata={},
    )
    with pytest.raises(ValueError, match="selectors missing"):
        taicang_culture(bad)
