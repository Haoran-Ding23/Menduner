"""Offline 好展会 (haozhanhui.com) adapter checks. Synthetic fixtures through MockTransport only.

These tests pin the adapter's fail-closed contract. The crux is provenance: an exhibition is
published only when its own detail page states a real interval, a 展会场馆 venue that is
explicitly in Suzhou, and a heading the page's own ``<title>`` agrees with. The listing row's
date is a start-day hint and is never used as the published interval, and the host's own status
badges (建议参加 / 好展会认证展会) are never part of an exhibition's name.
"""
from datetime import date, datetime, timezone

import httpx
import pytest

from crawler.extractor import extract
from crawler.http import PublicClient
from crawler.pipeline import run_pipeline
from crawler.schema import CollectedItem
from crawler.sources.exhibition import haozhanhui
from crawler.sources.exhibition.haozhanhui import HaozhanhuiSource

TODAY = date(2026, 10, 15)  # the day the live ground truth was verified
HOST = 'www.haozhanhui.com'
LISTING_URL = 'https://www.haozhanhui.com/zhanlanjihua/2026__suzhou__c_1.html'
HTML = {'Content-Type': 'text/html; charset=utf-8'}
ROBOTS_404 = '<!DOCTYPE html><html><head><title>404</title></head><body>404</body></html>'

# The verified listing row shape: start day, bracketed industry, then the record's own link.
LISTING_TEMPLATE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<title>2026年苏州展会信息_2026年苏州展览计划-好展会信息网</title></head><body>
<div class="zhanhui"><ul>{rows}</ul></div>
</body></html>"""

# The verified detail shape: heading, interval, then the labelled venue/organiser rows.
DETAIL_TEMPLATE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<title>【{name}】时间_地点_怎么样-好展会网</title></head><body>
<div class="exhname"><h1>{badges}{name}</h1></div>
<div class="exhinfotop">{interval}
<ul>
<li><strong>展会场馆：</strong><a href="https://www.haozhanhui.com/place/347.html">{venue}</a></li>
<li>，本展馆同期<strong>2</strong>个展会</li>
<li><strong>组织单位：</strong><a href="https://www.haozhanhui.com/org/105383.html">{organizer}</a></li>
<li><strong>官方网站：</strong>example.test</li>
</ul>
</div>
</body></html>"""


def listing_row(code='cdeiog', title='CLNB2027（第十二届）新能源产业博览会',
                day='2027-04-15', industry='能源矿产'):
    return f'<li>{day} 【{industry}】  <a href="/exh/exh_index_{code}.html" title="{title}">{title}</a></li>'


def listing_page(*rows):
    return LISTING_TEMPLATE.format(rows=''.join(rows))


def detail_page(name='CLNB2027（第十二届）新能源产业博览会', interval='2027-04-15~04-17',
                venue='苏州国际博览中心', organizer='上海有色网信息科技股份有限公司', badges=''):
    return DETAIL_TEMPLATE.format(name=name, interval=interval, venue=venue,
                                 organizer=organizer, badges=badges)


def record(raw, locator='CLNB2027（第十二届）新能源产业博览会', key='haozhanhui-cdeiog',
           url='https://www.haozhanhui.com/exh/exh_index_cdeiog.html'):
    return CollectedItem(item_key=key, original_url=url, source_name='haozhanhui',
                         crawl_time=datetime.now(timezone.utc), raw_content=raw,
                         extractor='haozhanhui_exhibition', locator=locator)


def client_for(handler):
    return PublicClient(transport=httpx.MockTransport(handler), interval=0,
                        sleep=lambda seconds: None)


def site_handler(listing, details, visited=None, robots=None):
    """Serve the city plan and its own detail pages; unknown routes answer 404."""
    def handler(request):
        if visited is not None:
            visited.append(str(request.url))
        if request.url.path == '/robots.txt':
            return (robots or (lambda r: httpx.Response(404, text=ROBOTS_404, headers=HTML)))(
                request)
        if request.url.path == '/zhanlanjihua/2026__suzhou__c_1.html':
            return httpx.Response(200, text=listing, headers=HTML)
        if request.url.path.startswith('/exh/'):
            body = details.get(request.url.path)
            if body is None:
                return httpx.Response(404, text='not found', headers=HTML)
            return httpx.Response(200, text=body, headers=HTML)
        return httpx.Response(404, text='not found', headers=HTML)
    return handler


def source_for(listing, details, *, max_items=3, visited=None, robots=None, today=TODAY):
    return HaozhanhuiSource(client=client_for(site_handler(listing, details, visited, robots)),
                            max_items=max_items, today=today)


DETAIL_PATH = '/exh/exh_index_cdeiog.html'


# --------------------------------------------------------------------------------------
# Extraction: explicit published fields only, never Verified
# --------------------------------------------------------------------------------------

def test_one_exhibition_is_published_with_its_own_published_fields():
    source = source_for(listing_page(listing_row()), {DETAIL_PATH: detail_page()}, max_items=1)
    try:
        collected = [item for item in source.collect() if item.is_event]
    finally:
        source.client.close()
    assert len(collected) == 1
    event = extract(collected[0], 'event_platform')
    # The shared extractor NFKC-normalises text, so the fullwidth （） the site prints are stored
    # as ASCII parentheses - the same convention every existing real source follows.
    assert event['event_name'] == 'CLNB2027(第十二届)新能源产业博览会'
    assert event['start_date'] == '2027-04-15' and event['end_date'] == '2027-04-17'
    assert event['venue'] == '苏州国际博览中心' and event['location'] == '苏州国际博览中心'
    assert event['organizer'] == '上海有色网信息科技股份有限公司'
    assert event['category'] == 'business'
    assert all(claim['status'] != 'Verified' for claim in event['field_evidence'].values())
    assert event['field_evidence']['end_date']['method'].startswith('explicit_published_interval')


def test_the_hosts_own_status_badges_are_not_part_of_the_name():
    """The live page puts 建议参加 / 好展会认证展会 inside the same h1 as the name."""
    raw = detail_page(name='CHInano2026第十六届中国国际纳米技术产业博览会',
                      interval='2026-10-21~10-23', organizer='中国微米纳米技术学会',
                      badges='<div class="exhjianyi">建议参加 好展会认证展会</div>')
    event = extract(record(raw, locator='CHInano2026第十六届中国国际纳米技术产业博览会',
                           key='haozhanhui-cddgho',
                           url='https://www.haozhanhui.com/exh/exh_index_cddgho.html'),
                    'event_platform')
    assert event['event_name'] == 'CHInano2026第十六届中国国际纳米技术产业博览会'
    assert '建议参加' not in event['event_name']


def test_a_row_name_and_heading_that_differ_only_in_brackets_are_the_same_exhibition():
    """【】 on the listing and （） on the detail are the same published name."""
    event = extract(record(detail_page(name='2026第23届苏州国际软包装技术与薄膜展览会'),
                           locator='2026第23届苏州国际软包装技术与薄膜展览会'),
                    'event_platform')
    assert event['event_name'] == '2026第23届苏州国际软包装技术与薄膜展览会'


@pytest.mark.parametrize('raw', [
    detail_page(interval='2027-04-15~'),                # no interval at all
    detail_page(interval='2027-04-15~03-01'),           # inverted interval
    detail_page(interval='2027-02-30~03-02'),           # impossible calendar day
    detail_page(venue='上海国家会展中心'),                 # not an explicit Suzhou venue
])
def test_only_a_real_suzhou_interval_is_published(raw):
    with pytest.raises(ValueError):
        haozhanhui.detail_record(raw)


def test_a_missing_organiser_stays_null_and_is_never_invented():
    raw = detail_page(organizer='').replace(
        '<li><strong>组织单位：</strong><a href="https://www.haozhanhui.com/org/105383.html">'
        '</a></li>', '<li><strong>展会场馆：</strong>'
                     '<a href="https://www.haozhanhui.com/place/347.html">'
                     '苏州国际博览中心</a></li>')
    start, end, venue, organizer, name = haozhanhui.detail_record(raw)
    assert organizer is None and venue == '苏州国际博览中心'
    assert (start, end) == ('2027-04-15', '2027-04-17')
    source = source_for(listing_page(listing_row()),
                        {DETAIL_PATH: raw}, max_items=1)
    try:
        collected = [item for item in source.collect() if item.is_event]
    finally:
        source.client.close()
    event = extract(collected[0], 'event_platform')
    assert event['organizer'] is None
    assert event['field_evidence']['organizer']['status'] == 'Missing'


@pytest.mark.parametrize('raw', [
    detail_page().replace('展会场馆：', '举办地点：'),
    detail_page().replace('【CLNB2027（第十二届）新能源产业博览会】', '【完全另一场展会】'),
    detail_page().replace('class="exhinfotop"', 'class="exhibits"'),
    detail_page().replace('class="exhname"', 'class="exhtitle"'),
])
def test_a_changed_detail_shape_fails_closed(raw):
    with pytest.raises(ValueError):
        haozhanhui.detail_record(raw)


def test_an_organizer_is_published_only_when_the_page_states_one():
    raw = detail_page(organizer='').replace(
        '<li><strong>组织单位：</strong><a href="https://www.haozhanhui.com/org/105383.html">'
        '</a></li>', '')
    start, end, venue, organizer, name = haozhanhui.detail_record(raw)
    assert organizer is None and venue == '苏州国际博览中心' and start == '2027-04-15'


def test_detail_url_and_heading_are_cross_checked():
    with pytest.raises(ValueError, match='listing row'):
        extract(record(detail_page(), locator='完全不同的一场展会'), 'event_platform')


# --------------------------------------------------------------------------------------
# URL allow-list
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize('url', [
    LISTING_URL,
    'https://www.haozhanhui.com/exh/exh_index_cdeiog.html',
])
def test_approved_public_routes_are_collectable(url):
    assert HaozhanhuiSource.is_public_url(url) is True


@pytest.mark.parametrize('url', [
    'http://www.haozhanhui.com/zhanlanjihua/2026__suzhou__c_1.html',
    'https://www.haozhanhui.com:444/zhanlanjihua/2026__suzhou__c_1.html',
    'https://evil.test/zhanlanjihua/2026__suzhou__c_1.html',
    'https://user:pw@www.haozhanhui.com/zhanlanjihua/2026__suzhou__c_1.html',
    # Another city's plan and another year are other routes, not this source's own.
    'https://www.haozhanhui.com/zhanlanjihua/2026__shanghai__c_1.html',
    'https://www.haozhanhui.com/zhanlanjihua/2027__suzhou__c_1.html',
    'https://www.haozhanhui.com/zhanlanjihua/2026__suzhou__c_2.html',
    'https://www.haozhanhui.com/zhanlanjihua/',
    # Venue and organiser pages are not exhibitions.
    'https://www.haozhanhui.com/place/347.html',
    'https://www.haozhanhui.com/org/105383.html',
    'https://www.haozhanhui.com/exh/exh_index_CDEIOG.html',
    'https://www.haozhanhui.com/exh/exh_index_cdeiog.html?page=2',
])
def test_unapproved_or_offhost_urls_are_never_collectable(url):
    assert HaozhanhuiSource.is_public_url(url) is False


# --------------------------------------------------------------------------------------
# Collection: bounds, date filtering and fail-closed shapes
# --------------------------------------------------------------------------------------

def test_listing_rows_are_read_in_the_sources_own_shape():
    rows = haozhanhui.listing_rows(listing_page(listing_row(), listing_row(code='cdejgl',
                                                                         title='另一场展会',
                                                                         day='2027-04-21')))
    assert rows == [
        {'date': '2027-04-15', 'industry': '能源矿产',
         'title': 'CLNB2027(第十二届)新能源产业博览会',
         'url': 'https://www.haozhanhui.com/exh/exh_index_cdeiog.html'},
        {'date': '2027-04-21', 'industry': '能源矿产', 'title': '另一场展会',
         'url': 'https://www.haozhanhui.com/exh/exh_index_cdejgl.html'},
    ]
    # A row's own href is resolved against the page it was served from, never assumed absolute.
    assert haozhanhui.listing_rows(listing_page(listing_row()),
                                    'https://www.haozhanhui.com/zhanlanjihua/x.html')[0]['url'] \
        == 'https://www.haozhanhui.com/exh/exh_index_cdeiog.html'


def test_the_industry_label_is_kept_for_the_record_it_belongs_to():
    """The 行业 label is a listing-row field with no home in the event schema.

    It reaches the extractor through the item key the same row is about, so the category rule
    can use the source's own label while the published record carries only the mapped category.
    """
    source = source_for(listing_page(listing_row()), {DETAIL_PATH: detail_page()}, max_items=1)
    try:
        items = source.collect()
    finally:
        source.client.close()
    events = [item for item in items if item.is_event]
    assert [item.item_key for item in events] == ['haozhanhui-cdeiog']
    assert haozhanhui.industry_by_key['haozhanhui-cdeiog'] == '能源矿产'
    event = extract(events[0], 'event_platform')
    assert event['category'] == 'business'
    assert 'industry=能源矿产' in event['field_evidence']['category']['snippet']
    # The label is not smuggled into the record as a field of its own.
    assert '行业' not in event and 'industry' not in event


def test_a_missing_industry_label_falls_back_to_the_title_then_to_others():
    assert haozhanhui.category_of(None, '苏州国际纳米技术产业博览会') == (
        'others', 'no_explicit_category_keyword_default_others')
    assert haozhanhui.category_of(None, '苏州国际音乐艺术展')[0] == 'culture'
    assert haozhanhui.category_of('文化艺术', '任意标题')[0] == 'culture'
    assert haozhanhui.category_of('未知行业', '2026苏州体育用品博览会')[0] == 'sports'


def test_past_dated_exhibitions_are_dropped_and_the_rest_are_published():
    """The plan page reaches back years; a finished exhibition is never republished."""
    listing = listing_page(
        listing_row(code='cddgho', title='已结束的展会', day='2018-05-16'),
        listing_row(code='cdeiog', title='即将举办的展会', day='2027-04-15'))
    details = {'/exh/exh_index_cddgho.html': detail_page(name='已结束的展会',
                                                         interval='2018-05-16~05-18'),
               DETAIL_PATH: detail_page(name='即将举办的展会', interval='2027-04-15~04-17')}
    visited = []
    source = source_for(listing, details, max_items=5, visited=visited)
    try:
        items = source.collect()
    finally:
        source.client.close()
    assert source.investigation['past_dated_rows_dropped'] == 1
    assert all('cddgho' not in url for url in visited), visited
    assert [item.item_key for item in items if item.is_event] == ['haozhanhui-cdeiog']


def test_venue_and_organiser_rows_are_never_requested():
    listing = listing_page(
        listing_row(code='cdeiog', title='展会一'),
        '<li>2027-04-15 【能源矿产】 <a href="/place/347.html">苏州国际博览中心</a></li>',
        '<li>2027-04-15 【能源矿产】 <a href="/org/105383.html">主办方</a></li>',
        '<li>2027-04-15 【能源矿产】 <a href="https://mp.weixin.qq.com/s/abc">外部</a></li>')
    visited = []
    source = source_for(listing, {DETAIL_PATH: detail_page(name='展会一')}, max_items=5,
                        visited=visited)
    try:
        items = source.collect()
    finally:
        source.client.close()
    assert source.investigation['rows_outside_suzhou_route_dropped'] == 3
    assert not any('/place/' in url or '/org/' in url or 'weixin' in url for url in visited)
    assert [item.item_key for item in items if item.is_event] == ['haozhanhui-cdeiog']


def test_max_items_bounds_detail_requests_and_the_listing_is_read_once():
    codes = ['cdei%02d' % number for number in range(1, 6)]
    listing = listing_page(*[listing_row(code=code, title='展会%s' % code) for code in codes])
    details = {'/exh/exh_index_%s.html' % code:
               detail_page(name='展会%s' % code, interval='2027-04-15~04-17')
               for code in codes}
    visited = []
    source = source_for(listing, details, max_items=2, visited=visited)
    try:
        items = source.collect()
    finally:
        source.client.close()
    assert source.investigation['candidate_detail_urls'] == 5
    assert source.investigation['detail_pages_fetched'] == 2
    assert len([url for url in visited if '/exh/' in url]) == 2
    assert len([url for url in visited if 'zhanlanjihua' in url]) == 1
    assert len([item for item in items if item.is_event]) == 2


def test_a_changed_listing_shape_fails_closed_with_an_explicit_reason():
    listing = '<!DOCTYPE html><html><body><p>2026年苏州展会信息</p></body></html>'
    source = source_for(listing, {})
    try:
        items = source.collect()
    finally:
        source.client.close()
    assert not [item for item in items if item.is_event]
    assert 'verified row shape' in source.errors[0]['error']


def test_a_stale_detail_is_recorded_without_discarding_the_verified_rest(tmp_path):
    listing = listing_page(listing_row(code='cdeiog', title='展会一'),
                           listing_row(code='cdejgl', title='展会二', day='2027-04-21'))
    details = {DETAIL_PATH: detail_page(name='展会一')}  # the second detail is gone
    source = source_for(listing, details, max_items=5)
    try:
        report = run_pipeline(tmp_path / 'haozhanhui.sqlite3', [source],
                              request_client=source.client)
    finally:
        source.client.close()
    assert report['eventsProcessed'] == 1 and report['eventsStored'] == 1
    assert report['attempts'][0]['status'] == 'Partial'
    assert '404' in report['attempts'][0]['error']


def test_an_access_wall_is_retained_as_raw_material_and_never_extracted():
    """A walled detail page is fetched and refused at collection time, with its reason recorded.

    The page is not published and not handed to extraction as if it were about an exhibition:
    the run reports the wall and the raw response stays available for a reviewer.
    """
    wall = ('<!DOCTYPE html><html><head><meta charset="utf-8"><title>验证</title></head><body>'
            '<p>请先登录后查看展会信息</p></body></html>')

    def handler(request):
        if request.url.path == '/robots.txt':
            return httpx.Response(404, text=ROBOTS_404, headers=HTML)
        if request.url.path.endswith('c_1.html'):
            return httpx.Response(200, text=listing_page(listing_row()), headers=HTML)
        return httpx.Response(200, text=wall, headers=HTML)

    source = HaozhanhuiSource(client=client_for(handler), max_items=1, today=TODAY)
    try:
        items = source.collect()
    finally:
        source.client.close()
    assert source.investigation['detail_pages_fetched'] == 1
    assert [item.item_key for item in items] == [
        'robots:https://www.haozhanhui.com', 'haozhanhui-listing']
    assert [item for item in items if item.is_event] == []
    assert source.errors and 'access wall' in source.errors[-1]['error']


def test_a_robots_disallow_stops_the_host_before_any_page_request():
    visited = []
    source = source_for(listing_page(listing_row()), {DETAIL_PATH: detail_page()},
                        robots=lambda request: httpx.Response(
                            200, text='User-agent: *\nDisallow: /\n', headers=HTML),
                        visited=visited)
    try:
        items = source.collect()
    finally:
        source.client.close()
    assert visited == ['https://www.haozhanhui.com/robots.txt']
    assert not [item for item in items if item.is_event]
    assert 'disallows' in source.errors[0]['error']


def test_source_configuration_is_validated():
    with pytest.raises(ValueError, match='today'):
        HaozhanhuiSource(client=object(), today='2026-10-15')
    source = HaozhanhuiSource(client=object(), today=TODAY)
    assert source.calendar_today == TODAY
    assert source.crawl_url == LISTING_URL
    assert source.source_id == 'platform-haozhanhui-suzhou'


# --------------------------------------------------------------------------------------
# End-to-end through the shared extractor/validator/pipeline contract
# --------------------------------------------------------------------------------------

def test_shared_extractor_and_pipeline_publish_one_unified_never_verified_event(tmp_path):
    raw = detail_page()
    event = extract(record(raw), 'event_platform')
    assert event['start_date'] == '2027-04-15' and event['venue'] == '苏州国际博览中心'

    source = source_for(listing_page(listing_row()), {DETAIL_PATH: raw}, max_items=1)
    try:
        report = run_pipeline(tmp_path / 'haozhanhui-e2e.sqlite3', [source],
                              request_client=source.client)
    finally:
        source.client.close()
    assert report['eventsProcessed'] == 1 and report['eventsCreated'] == 1
    assert report['eventsStored'] == 1 and report['itemsRejected'] == 0
    assert report['status'] == 'Success'
    assert report['evidenceRecordsGenerated'] == 10  # the ten contract fields
