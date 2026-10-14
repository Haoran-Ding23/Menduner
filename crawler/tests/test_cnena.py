"""Offline CNENA checks. Synthetic gb2312 fixtures through MockTransport, never live access.

These tests pin the fail-closed contract of the adapter: only an explicit ``开幕`` label is an
event date (never a publication/member timestamp), a schedule row without one is rejected with a
recorded reason, only path-based same-host routes are ever requested, and nothing this commercial
aggregator publishes can be ``Verified``.
"""
from datetime import datetime, timezone

import httpx
import pytest

from backend.database import connect
from crawler.extractor import extract
from crawler.http import PublicClient
from crawler.pipeline import run_pipeline
from crawler.schema import CollectedItem
from crawler.sources.exhibition import cnena
from crawler.sources.exhibition.cnena import (
    CnenaSource,
    VENUE_PATH,
    VENUE_URL,
    cnena_exhibition,
    detail_url,
    schedule_rows,
    venue_page_identity,
)

HOST = cnena.HOST
DETAIL_ROUTE = '/showroom/bencandy-htm-fid-1-id-48684.html'
DETAIL_URL = 'http://www.cnena.com' + DETAIL_ROUTE
VENUE_TITLE = '苏州国际博览中心_2026年展会信息|门票|参展|展馆地址|排期_CNENA会展门户'
ROBOTS_EMPTY = ''  # the live robots.txt is a 0-byte 200: no directives at all
ROBOTS_DENY = 'User-agent: *\nDisallow: /\n'


def schedule_row(title='2026装备制造业先进技术(苏州)展览会EMTE2026', opening='2026-12-04',
                 href='bencandy-htm-fid-1-id-48684.html', member='会员：万展汇', third=None):
    cell = third if third is not None else ('开幕：' + opening if opening else '时间待定')
    return ('<tr><td><a href="%s">%s</a></td><td>%s</td><td>%s</td></tr>'
            % (href, title, member, cell))


def venue_page(rows=None, title=VENUE_TITLE, name='苏州国际博览中心', extra=''):
    rows = [schedule_row()] if rows is None else rows
    return ('<!DOCTYPE html><html><head><meta http-equiv="Content-Type" '
            'content="text/html; charset=gb2312"><title>' + title + '</title></head><body>'
            '<div class="base"><b>展馆名称：</b><a href="" target="_blank" class="base">' + name +
            '</a><br></div>'
            '<a href="http://www.cnena.com/showroom/list_city.php?cityid=49">江苏展会</a>'
            '<table class="drag">' + ''.join(rows) + '</table>' + extra + '</body></html>')


def detail_page(title='2026装备制造业先进技术(苏州)展览会EMTE2026', opening='2026-12-04',
                ending='2026-12-06', venue='苏州国际博览中心', organizer='中国机械工业联合会',
                publish='2026-10-09 14:09:51', heading='h2',
                body='<p>展会介绍：2026装备制造业先进技术展览会定于2026年12月3日至6日在江苏省苏州市举办。</p>'):
    overview = ''
    if opening is not None:
        overview += '开幕日期：' + opening + '<br>'
    if ending is not None:
        overview += '结束日期：' + ending + '<br>'
    if venue is not None:
        overview += ('展会地点：<a href="http://www.cnena.com/showroom/showroom.php?id=28" '
                     'target="_blank">' + venue + '</a><br>')
    organization = ('<p>  主办单位：<br>' + organizer + ' <br>联合主办：<br>工业和信息化部装备工业发展'
                    '中心</p>') if organizer else '<p>暂无</p>'
    tip = ('<p><strong>温馨提示：</strong>本展会信息由CNENA会员【万展汇】于' + publish +
           '发布。展会将于2026-12-04在苏州国际博览中心举行，建议您在展前三个月开始准备参展事宜！</p>'
           ) if publish else ''
    return ('<!DOCTYPE html><html><head><meta http-equiv="Content-Type" '
            'content="text/html; charset=gb2312">'
            '<title>2026苏州装备制造展-' + title + '欢迎您</title></head><body>'
            '<div class="sub-info-2"><' + heading + '>' + title + '</' + heading + '></div>'
            '<div class="sub-info-2"><div class="mod-hd"><div class="mod-hd-title">展会概况：'
            '</div></div><div><p>' + overview + '</p></div></div>'
            '<div class="sub-info-2"><div class="mod-hd"><div class="mod-hd-title">组织机构：'
            '</div></div><div>' + organization + '</div></div>'
            + tip + body + '</body></html>')


def record(raw, url=DETAIL_URL, locator='2026-12-04', extractor='cnena_exhibition'):
    return CollectedItem(item_key='cnena-fair-48684', original_url=url,
                         source_name='China Exhibition Network',
                         crawl_time=datetime.now(timezone.utc), raw_content=raw,
                         extractor=extractor, locator=locator)


def client_for(handler, *, plain=True, **kwargs):
    if plain:
        kwargs.setdefault('plain_http_hosts', (HOST,))
    return PublicClient(transport=httpx.MockTransport(handler), interval=0,
                        sleep=lambda seconds: None, **kwargs)


def gb(body, status=200):
    """The live host serves charset=gb2312; the body is real gb2312 bytes, not a str."""
    return httpx.Response(status, content=body.encode('gb2312'),
                          headers={'Content-Type': 'text/html; charset=gb2312'})


def handler_for(visited, *, venue=None, details=None, robots=ROBOTS_EMPTY, venue_status=200):
    details = details if details is not None else {DETAIL_ROUTE: detail_page()}

    def handler(request):
        visited.append(str(request.url))
        if request.url.path == '/robots.txt':
            return httpx.Response(200, content=robots.encode('ascii'),
                                  headers={'Content-Type': 'text/plain'})
        if request.url.path == VENUE_PATH:
            return gb(venue if venue is not None else venue_page(), venue_status)
        return gb(details.get(request.url.path, detail_page()))

    return handler


# --------------------------------------------------------------------------------------
# Pure extraction: explicit labelled fields only, full provenance, never Verified
# --------------------------------------------------------------------------------------

def test_explicit_opening_and_closing_dates_publish_with_full_provenance():
    event = cnena_exhibition(record(detail_page()))
    assert event['event_name'] == '2026装备制造业先进技术(苏州)展览会EMTE2026'
    assert event['start_date'] == '2026-12-04' and event['end_date'] == '2026-12-06'
    assert event['venue'] == '苏州国际博览中心' and event['location'] == '苏州国际博览中心'
    assert event['organizer'] == '中国机械工业联合会'
    assert event['category'] == 'business'
    assert event['venue_id'] is None and event['district_id'] is None
    assert event['source_url'] == DETAIL_URL
    # The city is deliberately null: the only city evidence is the venue string.
    assert 'city' not in event or event['city'] is None
    for field, claim in event['field_evidence'].items():
        assert 0 <= claim['confidence'] <= 1, field
        assert claim['status'] in ('Unverified', 'Needs Review', 'Missing'), field
        assert claim['status'] != 'Verified', field
        assert claim['method'], field
    assert '开幕日期:2026-12-04' in event['field_evidence']['start_date']['snippet']
    assert '结束日期:2026-12-06' in event['field_evidence']['end_date']['snippet']
    assert '苏州国际博览中心' in event['field_evidence']['venue']['snippet']
    assert '中国机械工业联合会' in event['field_evidence']['organizer']['snippet']
    assert event['field_evidence']['organizer']['status'] == 'Needs Review'
    assert event['field_evidence']['category']['status'] == 'Needs Review'
    assert event['field_evidence']['start_date']['method'].startswith('explicit_labelled_opening')
    assert event['field_evidence']['source_url']['status'] == 'Unverified'


def test_publication_timestamp_is_never_used_as_an_event_date():
    raw = detail_page(opening=None, ending='2026-12-06')
    assert '于2026-10-09 14:09:51发布' in raw  # the timestamp really is on the page
    with pytest.raises(ValueError, match='never used as event dates'):
        cnena_exhibition(record(raw))


@pytest.mark.parametrize('raw', [
    detail_page(opening=None, ending=None),
    detail_page(opening=None, ending=None, publish='2026-12-04 08:00:00'),
    detail_page(opening='时间：12月4日至6日', ending=None),
    detail_page(opening='2026-02-30', ending='2026-03-01'),
])
def test_missing_ambiguous_or_invalid_opening_dates_are_rejected(raw):
    with pytest.raises(ValueError):
        cnena_exhibition(record(raw))


def test_the_publish_date_is_never_substituted_even_when_a_label_is_present():
    event = cnena_exhibition(record(
        detail_page(body='<p>本展会信息由CNENA会员【万展汇】于2026-10-09 14:09:51发布。</p>')))
    assert event['start_date'] == '2026-12-04'
    assert '2026-10-09' not in str(event['field_evidence']['start_date']['snippet'])


def test_detail_page_without_the_labelled_venue_is_rejected():
    with pytest.raises(ValueError, match='展会地点'):
        cnena_exhibition(record(detail_page(venue=None)))


def test_detail_page_without_an_exhibition_heading_is_rejected():
    with pytest.raises(ValueError, match='heading'):
        cnena_exhibition(record(detail_page(heading='h3')))


def test_closing_date_before_the_opening_date_is_rejected():
    with pytest.raises(ValueError, match='precedes'):
        cnena_exhibition(record(detail_page(opening='2026-12-06', ending='2026-12-04')))


def test_member_publisher_is_never_treated_as_the_organizer():
    raw = detail_page(organizer=None, publish='2026-10-09 14:09:51')
    assert '组织机构' in raw and 'CNENA会员' in raw
    event = cnena_exhibition(record(raw))
    # The row's 会员 account and the publishing member are publisher metadata, not a source name.
    assert event['organizer'] is None
    assert event['field_evidence']['organizer']['status'] == 'Missing'
    assert event['field_evidence']['organizer']['snippet'] is None


def test_detail_page_locator_must_match_the_discovered_row_date():
    with pytest.raises(ValueError, match='does not match'):
        cnena_exhibition(record(detail_page(opening='2026-12-05'), locator='2026-12-04'))


@pytest.mark.parametrize('url', [
    'https://www.cnena.com/showroom/bencandy-htm-fid-1-id-48684.html',
    'http://www.cnena.com:8080/showroom/bencandy-htm-fid-1-id-48684.html',
    'http://www.cnena.com/showroom/bencandy-htm-fid-1-id-48684.html?token=x',
    'http://m.cnena.com/showroom/bencandy-htm-fid-1-id-48684.html',
    'http://evil.test/showroom/bencandy-htm-fid-1-id-48684.html',
    'http://www.cnena.com/Show/city/suzhou/',
    'http://www.cnena.com/showroom/list_city-htm-cityid-49.html',
    'http://user:pw@www.cnena.com/showroom/bencandy-htm-fid-1-id-48684.html',
])
def test_only_approved_public_cnena_urls_are_collected(url):
    assert CnenaSource.is_public_url(url) is False
    assert CnenaSource.is_public_url(VENUE_URL) is True
    assert CnenaSource.is_public_url(DETAIL_URL) is True


def test_extraction_refuses_even_valid_html_from_an_unapproved_route():
    with pytest.raises(ValueError, match='approved public detail page'):
        cnena_exhibition(record(detail_page(),
                                url='http://www.cnena.com/Show/city/suzhou/'))


def test_access_wall_is_retained_but_never_extracted():
    raw = detail_page().replace('<body>', '<body><p>请先登录后查看</p>')
    with pytest.raises(ValueError, match='access wall'):
        cnena_exhibition(record(raw))


@pytest.mark.parametrize('title,expected', [
    ('2026苏州国际珠宝首饰玉石展览会', 'business'),
    ('2026装备制造业先进技术(苏州)展览会EMTE2026', 'business'),
    ('2026第23届苏州国际塑料橡胶工业展', 'business'),  # the title itself ends in 展
    ('第十五届苏州文化创意设计产业交易博览会(苏州文博会)', 'culture'),
    ('2026苏州国际工艺品鉴赏会', 'others'),
    ('2026苏州会展产业发展', 'others'),  # 发展 is not an exhibition suffix
])
def test_category_comes_from_explicit_title_keywords_or_defaults_to_others(title, expected):
    event = cnena_exhibition(record(detail_page(title=title)))
    assert event['category'] == expected
    assert event['field_evidence']['category']['status'] == 'Needs Review'
    if expected == 'others':
        assert 'default' in event['field_evidence']['category']['snippet']


# --------------------------------------------------------------------------------------
# Schedule-page parsing: explicit 开幕 rows, recorded rejections, no invented links
# --------------------------------------------------------------------------------------

def test_schedule_rows_require_the_explicit_opening_label_and_record_rejections():
    page = venue_page(rows=[
        schedule_row(),
        schedule_row(title='2026苏州国际茶产业博览会', opening=None,
                     href='bencandy-htm-fid-1-id-47207.html'),
        schedule_row(title='2027涡轮技术大会', opening='2027-06-01',
                     href='bencandy-htm-fid-1-id-48227.html', third='开幕：待定'),
    ])
    rows, rejected = schedule_rows(page)
    assert [row['opening'] for row in rows] == ['2026-12-04']
    assert [row['title'] for row in rejected] == ['2026苏州国际茶产业博览会', '2027涡轮技术大会']
    assert all('开幕' in item['reason'] for item in rejected)
    assert rows[0]['id'] == '48684' and rows[0]['url'] == DETAIL_URL
    assert rows[0]['member'].endswith('万展汇')  # NFKC normalises the full-width colon


def test_layout_rows_without_a_single_detail_link_are_not_schedule_rows():
    page = venue_page(rows=[
        '<tr><td>媒体中心 <a href="bencandy-htm-fid-1-id-1.html">a</a>'
        '<a href="bencandy-htm-fid-1-id-2.html">b</a></td><td>x</td><td>开幕：2026-12-04</td></tr>',
        '<tr><td>页脚</td><td>x</td><td>开幕：2026-12-04</td></tr>',
        schedule_row(),
    ])
    rows, rejected = schedule_rows(page)
    assert len(rows) == 1 and rejected == []


@pytest.mark.parametrize('href', [
    'bencandy-htm-fid-1-id-48684.html?token=x',
    'http://evil.test/showroom/bencandy-htm-fid-1-id-48684.html',
    'https://www.cnena.com/showroom/bencandy-htm-fid-1-id-48684.html',
    'showroom.php?id=28',
    'javascript:void(0)',
])
def test_query_string_off_host_and_off_route_links_never_resolve_to_a_request(href):
    assert detail_url(href) is None


def test_venue_page_identity_needs_both_the_title_and_the_labelled_name():
    assert venue_page_identity(venue_page()) == '苏州国际博览中心'
    assert venue_page_identity(venue_page(title='中国会展门户_展会信息')) is None
    assert venue_page_identity(venue_page(name='上海国家会展中心')) is None


# --------------------------------------------------------------------------------------
# Adapter collection: bounded detail requests, robots, redirects, gb2312, stop conditions
# --------------------------------------------------------------------------------------

def test_venue_page_and_bounded_details_are_fetched_without_any_query_string(tmp_path):
    visited = []
    second = '/showroom/bencandy-htm-fid-1-id-48227.html'
    rows = [schedule_row(),
            schedule_row(title='2027涡轮技术大会', opening='2027-06-01',
                         href=second.rsplit('/', 1)[1]),
            schedule_row(title='2026第九届苏州国际数控机床展览会', opening='2026-11-18',
                         href='bencandy-htm-fid-1-id-47333.html')]
    details = {DETAIL_ROUTE: detail_page(),
               second: detail_page(title='2027涡轮技术大会暨民用航空发动机与燃气轮机展览会',
                                   opening='2027-06-01', ending='2027-06-03')}
    client = client_for(handler_for(visited, venue=venue_page(rows=rows), details=details))
    source = CnenaSource(client=client, max_items=2)
    try:
        report = run_pipeline(tmp_path / 'cnena.sqlite3', [source], request_client=client)
        assert report['attempts'][0]['accepted'] == 2
        assert report['attempts'][0]['rejected'] == 0
        assert source.investigation['detail_pages_fetched'] == 2
        assert source.investigation['schedule_rows_seen'] == 3
        assert source.investigation['supplied_city_route_requests'] == 0
        assert all('?' not in url for url in visited)
        assert 'bencandy-htm-fid-1-id-47333.html' not in ''.join(visited)  # past max_items
        assert visited[0] == 'http://www.cnena.com/robots.txt'
        assert VENUE_URL in visited
    finally:
        client.close()


def test_off_host_and_query_string_rows_are_never_requested():
    visited = []
    rows = [schedule_row(title='外部详情页', href='http://evil.test/showroom/bencandy-htm-fid-1-id-1.html'),
            schedule_row(title='带查询串', href='bencandy-htm-fid-1-id-48684.html?token=x'),
            schedule_row(title='2026苏州国际珠宝首饰玉石展览会', opening='2026-12-25',
                         href='bencandy-htm-fid-1-id-47999.html')]
    client = client_for(handler_for(visited, venue=venue_page(rows=rows)))
    source = CnenaSource(client=client, max_items=5)
    try:
        items = source.collect()
        assert [item.item_key for item in items if item.is_event] == ['cnena-fair-47999']
        assert 'evil.test' not in ''.join(visited) and '?' not in ''.join(visited)
    finally:
        client.close()


def test_redirect_leaving_the_host_is_rejected_without_requesting_the_target():
    visited = []

    def handler(request):
        visited.append(str(request.url))
        if request.url.path == '/robots.txt':
            return httpx.Response(200, content=b'', headers={'Content-Type': 'text/plain'})
        return httpx.Response(302, headers={'Location': 'http://evil.test/showroom/showroom-htm-id-28.html'})

    client = client_for(handler)
    source = CnenaSource(client=client)
    try:
        items = source.collect()
        assert not [item for item in items if item.is_event]
        assert 'evil.test' not in ''.join(visited)
        assert 'Cross-host redirect' in source.errors[0]['error']
    finally:
        client.close()


def test_scheme_changing_redirect_is_rejected_without_requesting_the_target():
    visited = []

    def handler(request):
        visited.append(str(request.url))
        if request.url.path == '/robots.txt':
            return httpx.Response(200, content=b'', headers={'Content-Type': 'text/plain'})
        return httpx.Response(302, headers={'Location': 'https://www.cnena.com' + VENUE_PATH})

    client = client_for(handler)
    source = CnenaSource(client=client)
    try:
        items = source.collect()
        assert not [item for item in items if item.is_event]
        assert not [url for url in visited if url.startswith('https://')]
        assert 'scheme' in source.errors[0]['error']
    finally:
        client.close()


def test_gb2312_pages_are_decoded_before_extraction(tmp_path):
    def handler(request):
        if request.url.path == '/robots.txt':
            return httpx.Response(200, content=b'', headers={'Content-Type': 'text/plain'})
        body = venue_page() if request.url.path == VENUE_PATH else detail_page()
        return httpx.Response(200, content=body.encode('gb2312'),
                              headers={'Content-Type': 'text/html; charset=gb2312'})

    client = client_for(handler)
    db = tmp_path / 'gb2312.sqlite3'
    try:
        report = run_pipeline(db, [CnenaSource(client=client, max_items=1)], request_client=client)
        assert report['eventsStored'] == 1 and report['eventsProcessed'] == 1
        with connect(db) as con:
            raw = con.execute(
                "SELECT raw_content FROM crawler_raw_items WHERE validation_status='Published'"
            ).fetchone()
            assert '苏州国际博览中心' in raw['raw_content']
            assert '展会地点' in raw['raw_content']
            assert '\ufffd' not in raw['raw_content']  # no replacement characters
    finally:
        client.close()


def test_empty_robots_file_is_no_rules_and_the_venue_page_is_still_fetched():
    visited = []
    client = client_for(handler_for(visited))
    source = CnenaSource(client=client, max_items=1)
    try:
        items = source.collect()
        assert visited[0] == 'http://www.cnena.com/robots.txt'
        assert VENUE_URL in visited
        assert [item.item_key for item in items if item.is_event] == ['cnena-fair-48684']
    finally:
        client.close()


def test_robots_denial_stops_the_host_before_any_page_request():
    visited = []
    client = client_for(handler_for(visited, robots=ROBOTS_DENY))
    source = CnenaSource(client=client, max_items=1)
    try:
        items = source.collect()
        assert visited == ['http://www.cnena.com/robots.txt']
        assert not [item for item in items if item.is_event]
        assert source.pages_collected == 0
        assert 'disallows' in source.errors[0]['error']
    finally:
        client.close()


def test_robots_redirect_is_not_followed():
    visited = []

    def handler(request):
        visited.append(str(request.url))
        return httpx.Response(302, headers={'Location': '/robots.txt?v=2'})

    client = client_for(handler)
    source = CnenaSource(client=client)
    try:
        assert not [item for item in source.collect() if item.is_event]
        assert visited == ['http://www.cnena.com/robots.txt']
        assert not source.client.robots
    finally:
        client.close()


def test_venue_page_shape_change_fails_closed_with_an_explicit_reason():
    visited = []
    client = client_for(handler_for(visited, venue=venue_page(rows=[])))
    source = CnenaSource(client=client, max_items=3)
    try:
        items = source.collect()
        assert not [item for item in items if item.is_event]
        assert 'page shape changed' in source.errors[0]['error']
        assert 'detail' not in ''.join(visited)
    finally:
        client.close()


def test_page_that_no_longer_identifies_the_venue_fails_closed():
    visited = []
    client = client_for(handler_for(visited, venue=venue_page(name='上海国家会展中心')))
    source = CnenaSource(client=client, max_items=3)
    try:
        items = source.collect()
        assert not [item for item in items if item.is_event]
        assert 'no longer identifies itself' in source.errors[0]['error']
        assert 'bencandy' not in ''.join(visited)
    finally:
        client.close()


def test_stock_client_without_the_plain_http_optin_fails_closed_without_any_request():
    visited = []

    def handler(request):  # pragma: no cover - any request is a test failure
        visited.append(str(request.url))
        raise AssertionError('no request may be made without the plain-HTTP opt-in')

    client = client_for(handler, plain=False)
    source = CnenaSource(client=client, max_items=1)
    try:
        items = source.collect()
        assert items == [] and source.pages_collected == 0
        assert visited == []
        assert 'plain_http' in source.errors[0]['error']
        assert cnena.PLAIN_HTTP_LIMITATION in source.investigation['transport']
    finally:
        client.close()


def test_registry_rewritten_crawl_url_is_recorded_and_the_configured_route_is_not_requested():
    visited = []
    client = client_for(handler_for(visited))
    source = CnenaSource(client=client, max_items=1)
    source.crawl_url = cnena.SUPPLIED_CITY_ROUTE
    try:
        items = source.collect()
        assert 'Show/city/suzhou' not in ''.join(visited)
        assert VENUE_URL in visited
        assert any('not the verified' in warning for warning in source.warnings)
        assert [item.item_key for item in items if item.is_event] == ['cnena-fair-48684']
    finally:
        client.close()


def test_one_unavailable_detail_page_does_not_hide_the_remaining_dated_rows(tmp_path):
    visited = []
    rows = [schedule_row(),
            schedule_row(title='2026第三届中国(苏州)工业母机供应链展览会', opening='2026-11-18',
                         href='bencandy-htm-fid-1-id-47207.html')]

    def handler(request):
        visited.append(str(request.url))
        if request.url.path == '/robots.txt':
            return httpx.Response(200, content=b'', headers={'Content-Type': 'text/plain'})
        if request.url.path == VENUE_PATH:
            return gb(venue_page(rows=rows))
        if request.url.path == DETAIL_ROUTE:
            return httpx.Response(404, text='not found')
        return gb(detail_page(title='2026第三届中国(苏州)工业母机供应链展览会(苏州工博会)',
                              opening='2026-11-18', ending='2026-11-20'))

    client = client_for(handler)
    source = CnenaSource(client=client, max_items=2)
    try:
        report = run_pipeline(tmp_path / 'partial.sqlite3', [source], request_client=client)
        assert report['attempts'][0]['accepted'] == 1
        assert report['eventsStored'] == 1
        with connect(tmp_path / 'partial.sqlite3') as con:
            rejected = con.execute(
                "SELECT error FROM crawler_raw_items WHERE validation_status='Rejected'").fetchone()
            assert rejected is None or '404' in rejected['error']
    finally:
        client.close()


# --------------------------------------------------------------------------------------
# End-to-end through the shared extractor/validator/pipeline contract
# --------------------------------------------------------------------------------------

def test_pipeline_publishes_unverified_evidence_and_never_verified_status(tmp_path):
    visited = []
    client = client_for(handler_for(visited))
    source = CnenaSource(client=client, max_items=1)
    db = tmp_path / 'pipeline.sqlite3'
    try:
        report = run_pipeline(db, [source], request_client=client)
        assert report['eventsProcessed'] == report['eventsCreated'] == 1
        assert report['eventsStored'] == 1
        assert report['evidenceRecordsGenerated'] == 10
        assert report['attempts'][0]['rejected'] == 0
        assert report['attempts'][0]['contextRecords'] == 1
        assert report['attempts'][0]['pagesCollected'] == 2
        with connect(db) as con:
            assert not con.execute('PRAGMA foreign_key_check').fetchall()
            raw = con.execute(
                "SELECT * FROM crawler_raw_items WHERE validation_status='Published'").fetchone()
            assert raw['original_url'] == DETAIL_URL and '开幕日期' in raw['raw_content']
            rows = con.execute('SELECT * FROM crawler_evidence').fetchall()
            assert {row['field_name'] for row in rows} >= {
                'event_name', 'start_date', 'end_date', 'venue', 'location', 'organizer',
                'source_url', 'category'}
            assert all(row['verification_status'] != 'Verified' for row in rows)
            assert all(row['source_url'] == DETAIL_URL for row in rows)
            assert all(row['confidence'] > 0 for row in rows
                       if row['verification_status'] != 'Missing')
            assert all(row['confidence'] == 0 for row in rows
                       if row['verification_status'] == 'Missing')
    finally:
        client.close()


def test_pipeline_records_a_rejected_detail_page_with_its_reason(tmp_path):
    visited = []

    def handler(request):
        visited.append(str(request.url))
        if request.url.path == '/robots.txt':
            return httpx.Response(200, content=b'', headers={'Content-Type': 'text/plain'})
        if request.url.path == VENUE_PATH:
            return gb(venue_page())
        return gb(detail_page(venue=None))

    client = client_for(handler)
    source = CnenaSource(client=client, max_items=1)
    db = tmp_path / 'rejected.sqlite3'
    try:
        report = run_pipeline(db, [source], request_client=client)
        assert report['eventsStored'] == 0 and report['attempts'][0]['rejected'] == 1
        assert report['attempts'][0]['status'] == 'Failed'  # require_events on tier 1
        with connect(db) as con:
            row = con.execute(
                "SELECT * FROM crawler_raw_items WHERE validation_status='Rejected'").fetchone()
            assert row and '展会地点' in row['error'] and '展会概况' in row['raw_content']
    finally:
        client.close()


def test_shared_extractor_dispatch_uses_the_cnena_key():
    event = extract(record(detail_page()), 'event_platform')
    assert event['start_date'] == '2026-12-04' and event['venue'] == '苏州国际博览中心'
    with pytest.raises(ValueError, match='Unsupported real extractor'):
        extract(record(detail_page(), extractor='not_a_real_extractor'), 'event_platform')


def test_the_adapter_declares_its_source_identity_and_plain_http_limitation():
    source = CnenaSource(client=object())
    assert source.source_id == 'platform-cnena-suzhou'
    assert source.extractor == 'cnena_exhibition'
    assert source.allow_plain_http is True
    assert source.crawl_url == VENUE_URL == 'http://www.cnena.com' + VENUE_PATH
    assert source.supplied_city_route == 'http://www.cnena.com/Show/city/suzhou/'
