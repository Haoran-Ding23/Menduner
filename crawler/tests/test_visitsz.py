"""Offline visitsz checks. Synthetic fixtures mirror the verified live markup.

The fixtures reproduce the two verified live hazards, so the tests pin real
behaviour rather than an idealised one:

* the calendar listing is NOT ordered by event date, so paging must be swept to
  the page cap instead of stopping at the first past-dated page; and
* an invalid detail id answers HTTP 200 with the SAME template and EMPTY labels,
  so HTTP 200 is never acceptance - a real ``时间`` date and a real ``地点`` value
  are both required before anything is published.

No test performs a live request: every page is served through ``httpx.MockTransport``.
"""
from datetime import date, datetime, timezone
import json

import httpx
import pytest

from backend.database import connect
from crawler.extractor import extract
from crawler.http import PublicClient
from crawler.pipeline import run_pipeline
from crawler.schema import CollectedItem
from crawler.sources.tourism import visitsz
from crawler.sources.tourism.visitsz import BASE_URL, LISTING_PATH, VisitszSource

TODAY = date(2026, 10, 13)  # the date the live ground truth was verified
LISTING_URL = BASE_URL + LISTING_PATH
DETAIL_URL = BASE_URL + '/festival-detail.aspx?id='
ROBOTS_URL = BASE_URL + '/robots.txt'
BAOLI_ID = '2026101009515301'
HTML = {'Content-Type': 'text/html; charset=utf-8'}
# The live host answers /robots.txt with this 404 HTML body (no rules at all).
ROBOTS_404 = ('<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN" '
              '"http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd"><html><head>'
              '<meta http-equiv="Content-Type" content="text/html; charset=utf-8" />'
              '<title>404</title></head><body><h1>404</h1></body></html>')

DETAIL_TEMPLATE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>苏州市旅游咨询服务中心</title></head>
<body>
<div class="content-outer activity"><div class="content">
<img src="UploadFile/Festival/2026/x.jpg" class="photo">
<div class="info-panel">
<header>
<h1>{name}</h1>
<hr>
<article class="intro">
<div class="entry introduction">来源：{credit}</div>
<div class="entry time">时间：{when}</div>
<div class="entry place">地点：{place}</div>
</article>
<hr>
</header>
<article class="details">{details}</article>
</div>
</div></div>
</body></html>"""

BAOLI_DETAILS = ('演出简介 没有一件乐器，只凭人声交织成乐。 演出详情 '
                 '演出时间：2026年11月7日19:30 '
                 '演出地点：苏州市吴中区东苑路1号苏州保利大剧院大剧场 '
                 '演出票价（元/人）：80/120/180/280 购票方式： 原信息链接： '
                 'https://mp.weixin.qq.com/s/87jCpIw8Ydk3LooRDLqD3A')


def detail_page(name='苏州保利大剧院：《音你而来》A-minor 人声乐团专场音乐会',
                credit='苏州保利大剧院微信号', when='2026-11-07',
                place='苏州市吴中区东苑路1号苏州保利大剧院大剧场',
                details=BAOLI_DETAILS):
    """The verified detail shape. Empty arguments reproduce the invalid-id template."""
    return DETAIL_TEMPLATE.format(name=name, credit=credit, when=when, place=place,
                                 details=details)


def boilerplate_page():
    """Exactly the verified invalid-id answer: HTTP 200, same template, empty labels."""
    return detail_page(name='', credit='', when='', place='', details='')


def listing_page(*rows):
    """The verified calendar listing shape; each row is (href, title, 活动时间 text)."""
    entries = ''.join(
        '<li><a href="%s">%s</a><div class="date"><div>%s</div></div></li>'
        % (href, title, when) for href, title, when in rows)
    return ('<!DOCTYPE html><html><head><meta charset="utf-8">'
            '<title>苏州市旅游咨询服务中心</title></head><body>'
            '<div class="content-outer list"><div class="content">'
            '<header><h2 class="chinese">节庆日历</h2></header><ul>' + entries + '</ul>'
            '<div class="pages"><a href="/festival-activity.aspx?page=662" class="last">末页</a>'
            '</div></div></div></body></html>')


def listing_row(item_id=BAOLI_ID, title='苏州保利大剧院：《音你而来》A-minor 人声乐团专场音乐会',
        when='2026-11-07'):
    return ('festival-detail.aspx?id=' + item_id, title, '活动时间：' + when)


def record(raw, item_id=BAOLI_ID, extractor='visitsz_detail'):
    return CollectedItem(item_key='visitsz-detail-' + item_id,
                         original_url=DETAIL_URL + item_id, source_name='visitsz',
                         crawl_time=datetime.now(timezone.utc), raw_content=raw,
                         extractor=extractor, locator=item_id)


def html_response(body):
    return httpx.Response(200, text=body, headers=HTML)


def client_for(handler):
    return PublicClient(transport=httpx.MockTransport(handler), interval=0,
                        sleep=lambda seconds: None)


def calendar_handler(pages, details, visited=None, robots=None):
    """Serve the calendar and its detail pages; undefined listing pages are empty."""
    def handler(request):
        if visited is not None:
            visited.append(str(request.url))
        if request.url.path == '/robots.txt':
            return (robots or (lambda r: httpx.Response(404, text=ROBOTS_404, headers=HTML)))(
                request)
        if request.url.path == LISTING_PATH:
            query = request.url.query.decode()
            number = int(query.split('=')[1]) if query else 1
            return html_response(listing_page(*pages.get(number, ())))
        if request.url.path == '/festival-detail.aspx':
            body = details.get(request.url.params['id'])
            if body is None:
                return httpx.Response(404, text='not found', headers=HTML)  # stale listing row
            return html_response(body)
        return httpx.Response(404, text='not found', headers=HTML)
    return handler


def source_for(pages, details, *, max_items=3, page_cap=12, visited=None, robots=None):
    return VisitszSource(client=client_for(calendar_handler(pages, details, visited, robots)),
                         max_items=max_items, page_cap=page_cap, today=TODAY)


# --------------------------------------------------------------------------------------
# Pure extraction: explicit fields only, full provenance, never Verified
# --------------------------------------------------------------------------------------

def test_single_date_record_is_accepted_with_explicit_fields_and_provenance():
    event = visitsz.visitsz_event(record(detail_page()))
    # The shared extractor NFKC-normalises text, so the page's fullwidth colon is stored
    # as an ASCII one - the same convention every existing real source follows.
    assert event['event_name'] == '苏州保利大剧院:《音你而来》A-minor 人声乐团专场音乐会'
    assert event['start_date'] == '2026-11-07' and event['end_date'] is None
    assert event['venue'] == '苏州保利大剧院'
    assert event['location'] == '苏州市吴中区东苑路1号苏州保利大剧院大剧场'
    assert event['category'] == 'culture'
    assert event['organizer'] is None  # 来源 is a WeChat credit, not an organiser
    assert event['venue_id'] is None and event['district_id'] is None
    assert event['source_url'] == DETAIL_URL + BAOLI_ID
    for field, claim in event['field_evidence'].items():
        assert 0 <= claim['confidence'] <= 1
        assert claim['status'] in ('Unverified', 'Missing', 'Needs Review')
        assert claim['status'] != 'Verified', field
        assert claim['method']
    assert event['field_evidence']['start_date']['snippet'] == '时间：2026-11-07'
    assert event['field_evidence']['location']['snippet'].startswith('地点：')
    assert event['field_evidence']['source_url']['snippet'] == DETAIL_URL + BAOLI_ID
    assert event['field_evidence']['venue']['status'] == 'Needs Review'
    assert event['field_evidence']['category']['status'] == 'Needs Review'


def test_source_credit_is_recorded_as_provenance_and_never_as_an_organizer():
    event = visitsz.visitsz_event(record(detail_page()))
    credit = event['field_evidence']['organizer']
    assert event['organizer'] is None and credit['status'] == 'Missing'
    assert '来源：苏州保利大剧院微信号' in credit['snippet']
    assert 'publisher credit, not an organiser claim' in credit['snippet']
    assert 'https://mp.weixin.qq.com/s/87jCpIw8Ydk3LooRDLqD3A' in credit['snippet']
    assert 'never requested' in credit['snippet']
    assert 'provenance_only' in credit['method']


def test_explicit_organizer_labels_in_the_body_are_used_instead():
    labelled = BAOLI_DETAILS.replace('演出简介', '主办单位：苏州市文化广电和旅游局 演出简介')
    event = visitsz.visitsz_event(record(detail_page(details=labelled)))
    assert event['organizer'] == '苏州市文化广电和旅游局'  # stops at the next word
    assert event['field_evidence']['organizer']['status'] == 'Needs Review'
    assert 'explicit_organiser_label' in event['field_evidence']['organizer']['method']
    # An explicit 由…主办 sentence is used too, but the 来源 credit never is.
    sentence = visitsz.visitsz_event(record(detail_page(
        details='本次展览由苏州吴文化博物馆与苏州弘化社慈善基金会联合主办，欢迎参观。')))
    assert sentence['organizer'] == '苏州吴文化博物馆与苏州弘化社慈善基金会'
    assert '来源：苏州保利大剧院微信号' not in (sentence['organizer'] or '')


def test_date_range_keeps_both_explicit_dates():
    when = '2026-12-04 - 2026-12-05'
    event = visitsz.visitsz_event(record(detail_page(
        name='苏州湾大剧院：英国经典惊悚剧《黑衣女人》', when=when,
        place='苏州市吴江区东太湖大道12000号苏州湾大剧院',
        details='演出简介 惊悚剧。 演出详情 演出时间：2026年12月4日19:30 12月5日14:30')))
    assert event['start_date'] == '2026-12-04' and event['end_date'] == '2026-12-05'
    assert event['field_evidence']['end_date']['snippet'] == '时间：' + when
    assert event['venue'] == '苏州湾大剧院'
    assert event['category'] == 'culture'


@pytest.mark.parametrize('when', [
    '',                         # the invalid-id template answers with an empty 时间
    '待定',
    '2026-11',
    '2026年11月7日',
    '11-07',
    '2026-02-30',               # not a real calendar date
    '2026-12-05 - 2026-12-04',  # inverted interval
    '2026-11-07（周六）',        # the label carries no bare interval
])
def test_no_explicit_usable_date_means_no_event(when):
    with pytest.raises(ValueError):
        visitsz.visitsz_event(record(detail_page(when=when)))


def test_boilerplate_invalid_id_page_is_rejected_even_though_it_is_http_200():
    raw = boilerplate_page()
    assert '<h1></h1>' in raw and '时间：</div>' in raw  # the live template is empty
    with pytest.raises(ValueError, match='boilerplate'):
        visitsz.visitsz_event(record(raw))


def test_a_named_page_without_a_date_or_place_is_rejected():
    with pytest.raises(ValueError, match='No explicit 时间'):
        visitsz.visitsz_event(record(detail_page(when='')))
    with pytest.raises(ValueError, match='No explicit 地点'):
        visitsz.visitsz_event(record(detail_page(place='')))


@pytest.mark.parametrize('place', ['详见文章', '（详见正文）', '待定', '另行通知', 'TBD'])
def test_placeholder_place_values_are_not_a_location_claim(place):
    with pytest.raises(ValueError, match='No explicit 地点'):
        visitsz.visitsz_event(record(detail_page(place=place)))


def test_detail_pages_without_the_verified_field_block_fail_closed():
    header_only = detail_page().replace('<article class="intro">', '<div class="intro">')
    with pytest.raises(ValueError, match='verified'):
        visitsz.visitsz_event(record(header_only))
    relabelled = detail_page().replace('时间：', '', 1)
    with pytest.raises(ValueError, match='No explicit 时间'):
        visitsz.visitsz_event(record(relabelled))
    no_place = detail_page().replace('地点：', '', 1)
    with pytest.raises(ValueError, match='No explicit 地点'):
        visitsz.visitsz_event(record(no_place))
    unknown_labels = (detail_page().replace('来源：', '出处：').replace('时间：', '日期：')
                      .replace('地点：', '场馆：'))
    with pytest.raises(ValueError, match='label rows'):
        visitsz.visitsz_event(record(unknown_labels))
    panel_gone = detail_page().replace('content-outer activity', 'content-outer activity-x')
    with pytest.raises(ValueError, match='verified'):
        visitsz.visitsz_event(record(panel_gone))


def test_only_approved_https_detail_urls_are_extracted():
    with pytest.raises(ValueError, match='approved public detail URL'):
        visitsz.visitsz_event(record(detail_page(), item_id='123'))
    offhost = CollectedItem(item_key='k', original_url='https://evil.test/festival-detail.aspx?id=' + BAOLI_ID,
                            source_name='visitsz', crawl_time=datetime.now(timezone.utc),
                            raw_content=detail_page(), extractor='visitsz_detail', locator=BAOLI_ID)
    with pytest.raises(ValueError, match='approved public detail URL'):
        visitsz.visitsz_event(offhost)


def test_detail_id_must_match_the_collected_locator():
    item = record(detail_page())
    item.locator = '2026101009599999'
    with pytest.raises(ValueError, match='locator'):
        visitsz.visitsz_event(item)


def test_access_wall_page_is_retained_but_never_extracted():
    walled = detail_page().replace('<h1>', '<h1>请先登录后查看 ')
    with pytest.raises(ValueError, match='access wall'):
        visitsz.visitsz_event(record(walled))


# --------------------------------------------------------------------------------------
# Category and venue: explicit page text only, otherwise 'others'
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize('name,category', [
    ('苏州保利大剧院：《音你而来》A-minor 人声乐团专场音乐会', 'culture'),
    ('苏州市评弹团：2026年10月下旬苏州评弹长篇书场讯息', 'culture'),
    ('苏州美术馆：墨舞人生——夏小斌绘画作品展', 'culture'),
    ('昆山戏曲百戏博物馆：重阳节系列活动——重阳雅集', 'folk'),
    ('苏州奥体中心：苏州城市足球联赛决赛', 'sports'),
    ('苏州图书馆：古籍修复公益讲座', 'education'),
])
def test_category_comes_from_explicit_title_keywords(name, category):
    assert visitsz.visitsz_event(record(detail_page(name=name)))['category'] == category


@pytest.mark.parametrize('name', [
    '苏州某单位：第三季度工作会议',
    '苏州市旅游咨询中心：通知',
])
def test_unmapped_titles_default_to_others_without_guessing(name):
    event = visitsz.visitsz_event(record(detail_page(name=name)))
    assert event['category'] == 'others'
    claim = event['field_evidence']['category']
    assert 'default_others' in claim['snippet'] and claim['status'] == 'Needs Review'


def test_venue_is_only_built_from_literal_page_text():
    # A title prefix that also occurs in the published 地点 is used verbatim.
    event = visitsz.visitsz_event(record(detail_page()))
    assert event['venue'] == '苏州保利大剧院'
    # Otherwise the address tail after the last street number is used verbatim.
    tail = visitsz.visitsz_event(record(detail_page(
        name='苏州奥体中心：某演唱会', place='苏州市工业园区中新大道东999号苏州奥林匹克体育中心体育馆')))
    assert tail['venue'] == '苏州奥林匹克体育中心体育馆'
    # No street number and no matching prefix: location is published, venue stays null.
    plain = visitsz.visitsz_event(record(detail_page(
        name='苏州某剧院：某音乐会', place='苏州工业园区星海街')))
    assert plain['venue'] is None and plain['location'] == '苏州工业园区星海街'
    assert plain['field_evidence']['venue']['status'] == 'Missing'


def test_body_time_lines_that_list_other_dates_are_flagged_not_hidden():
    details = ('演出简介 惊悚剧。 演出详情 演出时间：2026年11月28日（周六）19:30，'
               '2026年11月29日（周日）14:30 12月4日（周五）19:30（加场），'
               '12月5日（周六）14:30（加场） 演出地点：苏州市吴江区东太湖大道12000号苏州湾大剧院戏剧厅')
    event = visitsz.visitsz_event(record(detail_page(
        name='苏州湾大剧院：英国经典惊悚剧《黑衣女人》', when='2026-12-04 - 2026-12-05',
        place='苏州市吴江区东太湖大道12000号苏州湾大剧院', details=details)))
    assert event['start_date'] == '2026-12-04' and event['end_date'] == '2026-12-05'
    claim = event['field_evidence']['start_date']
    assert claim['status'] == 'Needs Review'
    assert claim['candidates'] == ['2026-11-28', '2026-11-29', '2026-12-04', '2026-12-05']
    assert '2026-11-28' in claim['snippet']
    assert 'within_source_body_time_lines' in claim['method']
    assert event['field_evidence']['end_date']['status'] == 'Needs Review'
    # A body line that agrees with the labelled interval is not flagged.
    agree = visitsz.visitsz_event(record(detail_page()))
    assert agree['field_evidence']['start_date']['status'] == 'Unverified'
    assert 'candidates' not in agree['field_evidence']['start_date']


# --------------------------------------------------------------------------------------
# URL allow-list
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize('url', [
    LISTING_URL,
    LISTING_URL + '?page=2',
    LISTING_URL + '?page=662',
    DETAIL_URL + BAOLI_ID,
])
def test_approved_public_routes_are_collectable(url):
    assert VisitszSource.is_public_url(url) is True


@pytest.mark.parametrize('url', [
    'http://visitsz.wglj.suzhou.com.cn/festival-activity.aspx',
    'https://visitsz.wglj.suzhou.com.cn:444/festival-activity.aspx',
    'https://www.visitsz.wglj.suzhou.com.cn/festival-activity.aspx',
    'https://evil.test/festival-activity.aspx',
    'https://visitsz.wglj.suzhou.com.cn/festival-activity.aspx?page=0',
    'https://visitsz.wglj.suzhou.com.cn/festival-activity.aspx?page=abc',
    'https://visitsz.wglj.suzhou.com.cn/festival-activity.aspx#frag',
    'https://user:pass@visitsz.wglj.suzhou.com.cn/festival-activity.aspx',
    'https://visitsz.wglj.suzhou.com.cn/other.aspx',
    'https://visitsz.wglj.suzhou.com.cn/festival-detail.aspx?id=123',
    'https://visitsz.wglj.suzhou.com.cn/festival-detail.aspx?id=' + BAOLI_ID + '0',
    'https://visitsz.wglj.suzhou.com.cn/festival-detail.aspx?id=' + BAOLI_ID + '&x=1',
    'https://visitsz.wglj.suzhou.com.cn/festival-detail.aspx',
    'https://mp.weixin.qq.com/s/87jCpIw8Ydk3LooRDLqD3A',
])
def test_unapproved_or_offhost_urls_are_never_collectable(url):
    assert VisitszSource.is_public_url(url) is False


# --------------------------------------------------------------------------------------
# Collection: bounded sweeping, date filtering, detail budget
# --------------------------------------------------------------------------------------

def test_calendar_is_swept_and_past_dated_rows_are_filtered_not_stopped():
    """Page 1 is entirely past-dated: paging must continue rather than stop there."""
    pages = {
        1: [listing_row('2026010100000001', '苏州某剧院：已结束演出', '2026-01-05'),
            listing_row('2026010100000002', '苏州某剧院：已结束展览', '2026-02-01 - 2026-02-10')],
        2: [listing_row('2026101300000003', '苏州某剧院：即将演出', '2026-12-01'),
            listing_row('2026101300000004', '苏州某剧院：已结束音乐会', '2026-03-01')],
    }
    details = {'2026101300000003': detail_page(
        name='苏州某剧院：即将演出', when='2026-12-01', place='苏州市某路1号苏州某剧院')}
    visited = []
    source = source_for(pages, details, max_items=5, visited=visited)
    try:
        items = source.collect()
    finally:
        source.client.close()
    assert [item.item_key for item in items if item.is_event] == ['visitsz-detail-2026101300000003']
    assert source.investigation['past_dated_listing_rows_dropped'] == 3
    assert source.investigation['listing_pages_fetched'] == 3  # pages 1, 2 and the empty page 3
    assert LISTING_URL + '?page=2' in visited
    assert [item.item_key for item in items if not item.is_event] == [
        'robots:' + BASE_URL, 'visitsz-listing-1', 'visitsz-listing-2', 'visitsz-listing-3']


def test_broken_listing_intervals_are_dropped_and_counted_never_repaired():
    """The live calendar holds one row whose 活动时间 is 2026-09-30 - 2026-09-29.

    An interval that cannot be real is dropped and reported, never repaired into a
    date, and it must not stop paging or look like a changed listing shape.
    """
    pages = {
        1: [('festival-detail.aspx?id=2026092910475901', '苏州某剧院：倒置区间', '活动时间：2026-09-30 - 2026-09-29'),
            ('festival-detail.aspx?id=2026092910475902', '苏州某剧院：不可能日期', '活动时间：2026-02-30'),
            ('festival-detail.aspx?id=2026092910475903', '苏州某剧院：没有日期标记', '时间待定'),
            listing_row('2026101300000007', '苏州某剧院：演出', '2026-12-01')],
        2: [listing_row('2026101300000008', '苏州某剧院：另一场演出', '2026-12-02')],
    }
    details = {'2026101300000007': detail_page(when='2026-12-01', name='苏州某剧院：演出',
                                               place='苏州市某路1号苏州某剧院'),
               '2026101300000008': detail_page(when='2026-12-02', name='苏州某剧院：另一场演出',
                                               place='苏州市某路1号苏州某剧院')}
    visited = []
    source = source_for(pages, details, max_items=5, page_cap=2, visited=visited)
    try:
        items = source.collect()
    finally:
        source.client.close()
    investigation = source.investigation
    assert investigation['inverted_interval_rows_dropped'] == 1
    assert investigation['impossible_date_rows_dropped'] == 1
    assert investigation['undated_listing_rows_dropped'] == 1
    assert investigation['listing_rows_seen'] == 5
    assert investigation['candidate_detail_urls'] == 2
    assert investigation['listing_pages_fetched'] == 2  # a bad row never looks like a shape change
    assert source.errors == []
    assert all('20260929' not in url for url in visited)
    assert [item.item_key for item in items if item.is_event] == [
        'visitsz-detail-2026101300000007', 'visitsz-detail-2026101300000008']


def test_page_cap_bounds_listing_requests():
    pages = {number: [listing_row('20261013000000%02d' % number, '苏州某剧院：演出%d' % number,
                          '2026-12-01')] for number in range(1, 6)}
    details = {'20261013000000%02d' % number: detail_page(
        when='2026-12-01', name='苏州某剧院：演出%d' % number, place='苏州市某路1号苏州某剧院')
        for number in range(1, 6)}
    visited = []
    source = source_for(pages, details, max_items=5, page_cap=2, visited=visited)
    try:
        items = source.collect()
    finally:
        source.client.close()
    assert source.investigation['page_cap'] == 2
    assert source.investigation['listing_pages_fetched'] == 2
    assert LISTING_URL + '?page=3' not in visited
    assert source.investigation['candidate_detail_urls'] == 2
    assert len([item for item in items if item.is_event]) == 2


def test_max_items_bounds_detail_page_requests():
    pages = {1: [listing_row('20261013000000%02d' % number, '苏州某剧院：演出%d' % number, '2026-12-01')
                 for number in range(1, 5)]}
    details = {'20261013000000%02d' % number: detail_page(
        when='2026-12-01', name='苏州某剧院：演出%d' % number, place='苏州市某路1号苏州某剧院')
        for number in range(1, 5)}
    visited = []
    source = source_for(pages, details, max_items=2, page_cap=1, visited=visited)
    try:
        items = source.collect()
    finally:
        source.client.close()
    assert source.investigation['candidate_detail_urls'] == 4
    assert source.investigation['detail_pages_fetched'] == 2
    assert len([url for url in visited if 'festival-detail.aspx' in url]) == 2
    assert len([item for item in items if item.is_event]) == 2


def test_offhost_and_wechat_row_links_are_never_requested():
    pages = {
        1: [('https://evil.test/festival-detail.aspx?id=2026101300000009', '外部', '活动时间：2026-12-01'),
            ('https://mp.weixin.qq.com/s/87jCpIw8Ydk3LooRDLqD3A', '微信原文', '活动时间：2026-12-01'),
            ('http://visitsz.wglj.suzhou.com.cn/festival-detail.aspx?id=2026101300000008', '明文', '活动时间：2026-12-01'),
            listing_row('2026101300000007', '苏州某剧院：演出', '2026-12-01')],
    }
    details = {'2026101300000007': detail_page(when='2026-12-01', name='苏州某剧院：演出',
                                               place='苏州市某路1号苏州某剧院')}
    visited = []
    source = source_for(pages, details, max_items=5, page_cap=1, visited=visited)
    try:
        items = source.collect()
    finally:
        source.client.close()
    assert source.investigation['offhost_or_invalid_row_links_dropped'] == 3
    assert source.investigation['wechat_requests'] == 0
    assert all('weixin' not in url and 'evil.test' not in url for url in visited)
    assert [item.item_key for item in items if item.is_event] == ['visitsz-detail-2026101300000007']


def test_robots_404_is_permissive_and_the_soft_404_opt_in_stays_off():
    visited = []
    source = source_for({1: [listing_row()]}, {BAOLI_ID: detail_page()}, max_items=1, page_cap=1,
                        visited=visited)
    try:
        items = source.collect()
    finally:
        source.client.close()
    assert VisitszSource.accept_soft_404_robots is False
    assert visited[0] == ROBOTS_URL
    assert source.pages_collected == 2
    assert [item.item_key for item in source.policy_items] == ['robots:' + BASE_URL]
    assert source.errors == []
    assert [item.item_key for item in items if item.is_event] == ['visitsz-detail-' + BAOLI_ID]


def test_robots_denial_stops_the_host_before_any_calendar_request():
    pages = {1: [listing_row()]}
    details = {BAOLI_ID: detail_page()}
    visited = []
    source = source_for(pages, details, max_items=1, page_cap=1, visited=visited,
                        robots=lambda request: httpx.Response(
                            200, text='User-agent: *\nDisallow: /\n', headers=HTML))
    try:
        items = source.collect()
    finally:
        source.client.close()
    # Only the robots policy text is retained; no calendar page and no detail is requested.
    assert [item.item_key for item in items if item.item_key.startswith('visitsz-')] == []
    assert visited == [ROBOTS_URL]
    assert 'disallows' in source.errors[0]['error']
    assert source.investigation['listing_pages_fetched'] == 0


def test_an_empty_calendar_page_stops_paging_without_an_error():
    pages = {1: [listing_row('2026101300000007', '苏州某剧院：演出', '2026-12-01')]}
    details = {'2026101300000007': detail_page(when='2026-12-01', name='苏州某剧院：演出',
                                               place='苏州市某路1号苏州某剧院')}
    source = source_for(pages, details, max_items=1)
    try:
        items = source.collect()
    finally:
        source.client.close()
    assert source.investigation['listing_pages_fetched'] == 2  # page 2 is the end of the calendar
    assert source.errors == [] and source.warnings == []
    assert [item.item_key for item in items if item.is_event] == ['visitsz-detail-2026101300000007']


def test_listing_shape_change_fails_closed_with_an_explicit_reason():
    """Rows without a parseable 活动时间, or no verified container, publish nothing."""
    undated_entries = ('<!DOCTYPE html><html><body>'
                       '<div class="content-outer list"><div class="content"><ul>'
                       '<li><a href="festival-detail.aspx?id=' + BAOLI_ID + '">某活动</a>'
                       '<div class="date"><div>活动时间：明天</div></div></li>'
                       '</ul></div></div></body></html>')

    def serve(body):
        def handler(request):
            if request.url.path == '/robots.txt':
                return httpx.Response(404, text=ROBOTS_404, headers=HTML)
            return html_response(body)
        return handler

    source = VisitszSource(client=client_for(serve(undated_entries)),
                           max_items=2, page_cap=1, today=TODAY)
    try:
        items = source.collect()
    finally:
        source.client.close()
    assert not [item for item in items if item.is_event]
    assert source.investigation['undated_listing_rows_dropped'] == 1
    assert '活动时间' in source.errors[0]['error']

    source = VisitszSource(client=client_for(
        serve(undated_entries.replace('content-outer list', 'content-outer x'))),
        max_items=2, page_cap=1, today=TODAY)
    try:
        items = source.collect()
    finally:
        source.client.close()
    assert not [item for item in items if item.is_event]
    assert 'verified' in source.errors[0]['error']


def test_a_stale_detail_url_is_recorded_without_discarding_the_verified_rest(tmp_path):
    pages = {1: [listing_row('2026010100000001', '苏州某剧院：已下线', '2026-12-01'),
                 listing_row('2026101300000007', '苏州某剧院：演出', '2026-12-01')]}
    details = {'2026101300000007': detail_page(when='2026-12-01', name='苏州某剧院：演出',
                                               place='苏州市某路1号苏州某剧院')}
    source = source_for(pages, details, max_items=5, page_cap=1)
    try:
        report = run_pipeline(tmp_path / 'stale.sqlite3', [source],
                              request_client=source.client)
        assert report['eventsProcessed'] == 1 and report['eventsStored'] == 1
        assert report['attempts'][0]['status'] == 'Partial'
        assert '404' in report['attempts'][0]['error']
        # Both detail URLs were requested; only the one that answered became an event.
        assert report['httpRequests'] == 4  # robots + 1 listing page + 2 detail pages
        assert report['attempts'][0]['investigation']['detail_pages_fetched'] == 1
    finally:
        source.client.close()


def test_source_configuration_is_validated():
    with pytest.raises(ValueError, match='page_cap'):
        VisitszSource(client=object(), page_cap=0)
    with pytest.raises(ValueError, match='today'):
        VisitszSource(client=object(), today='2026-10-13')


# --------------------------------------------------------------------------------------
# End-to-end through the shared extractor/validator/pipeline contract
# --------------------------------------------------------------------------------------

def test_shared_extractor_and_pipeline_publish_one_unified_never_verified_event(tmp_path):
    raw = detail_page()
    event = extract(record(raw), 'tourism')
    assert event['start_date'] == '2026-11-07' and event['venue'] == '苏州保利大剧院'
    assert event['source_url'] == DETAIL_URL + BAOLI_ID
    assert all(claim['status'] != 'Verified' for claim in event['field_evidence'].values())

    pages = {1: [listing_row()]}
    source = source_for(pages, {BAOLI_ID: raw}, max_items=1, page_cap=1)
    db = tmp_path / 'visitsz.sqlite3'
    try:
        report = run_pipeline(db, [source], request_client=source.client)
        assert report['eventsProcessed'] == 1 and report['eventsCreated'] == 1
        assert report['eventsStored'] == 1 and report['itemsRejected'] == 0
        assert report['status'] == 'Success'
        assert report['evidenceRecordsGenerated'] == 10  # the ten contract fields
        assert report['attempts'][0]['investigation']['wechat_requests'] == 0
        assert report['attempts'][0]['investigation']['detail_pages_fetched'] == 1
    finally:
        source.client.close()
    with connect(db) as con:
        assert not con.execute('PRAGMA foreign_key_check').fetchall()
        raw_row = con.execute(
            "SELECT * FROM crawler_raw_items WHERE validation_status='Published'").fetchone()
        assert raw_row['original_url'] == DETAIL_URL + BAOLI_ID
        assert raw_row['raw_content'] == raw
        assert con.execute(
            "SELECT COUNT(*) FROM crawler_raw_items WHERE validation_status='Context'").fetchone()[0] == 2
        evidence = con.execute('SELECT * FROM crawler_evidence').fetchall()
        assert {row['field_name'] for row in evidence} >= {
            'event_name', 'start_date', 'location', 'venue', 'category', 'organizer', 'source_url'}
        assert all(row['source_url'] == DETAIL_URL + BAOLI_ID for row in evidence)
        assert all(row['verification_status'] != 'Verified' for row in evidence)
        # put_evidence keeps the snippet/method provenance the pipeline itself drops.
        legacy = {json.loads(row['payload'])['field']: json.loads(row['payload'])
                  for row in con.execute("SELECT payload FROM evidence WHERE field IN ('organizer','startDate','sourceUrl')")}
        assert legacy['organizer']['value'] is None
        assert '来源：苏州保利大剧院微信号' in legacy['organizer']['snippet']
        assert 'provenance_only' in legacy['organizer']['method']
        assert legacy['startDate']['value'] == '2026-11-07'
        assert legacy['startDate']['snippet'] == '时间：2026-11-07'
        assert 'explicit_labelled_detail_time' in legacy['startDate']['method']
        assert legacy['sourceUrl']['value'] == DETAIL_URL + BAOLI_ID
        assert con.execute("SELECT verification_status FROM events").fetchone()[0] != 'Verified'


def test_pipeline_never_publishes_the_invalid_id_page_and_says_why(tmp_path):
    source = source_for({1: [listing_row()]}, {BAOLI_ID: boilerplate_page()}, max_items=1, page_cap=1)
    db = tmp_path / 'visitsz-bad.sqlite3'
    try:
        report = run_pipeline(db, [source], request_client=source.client)
        assert report['eventsProcessed'] == 0 and report['eventsStored'] == 0
        assert report['itemsRejected'] == 1
        assert report['attempts'][0]['status'] == 'Failed'
    finally:
        source.client.close()
    with connect(db) as con:
        row = con.execute('SELECT * FROM crawler_raw_items WHERE validation_status=?',
                          ('Rejected',)).fetchone()
        assert row['original_url'] == DETAIL_URL + BAOLI_ID
        assert 'boilerplate' in row['error']
        assert con.execute('SELECT COUNT(*) FROM events').fetchone()[0] == 0


def test_pipeline_reports_a_failed_source_when_no_event_survives_extraction(tmp_path):
    """require_events keeps a source that yields nothing from looking successful."""
    source = source_for({1: [listing_row()]}, {BAOLI_ID: detail_page(when='待定')},
                        max_items=1, page_cap=1)
    db = tmp_path / 'visitsz-undated.sqlite3'
    try:
        assert source.require_events is True
        report = run_pipeline(db, [source], request_client=source.client)
        assert report['status'] == 'Failed' and report['eventsStored'] == 0
        assert report['attempts'][0]['status'] == 'Failed'
    finally:
        source.client.close()
