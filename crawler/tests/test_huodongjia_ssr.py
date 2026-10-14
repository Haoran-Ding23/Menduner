"""Offline Huodongjia SSR checks. Synthetic ``__NEXT_DATA__`` fixtures, never live access.

These tests pin the fail-closed contract of the rewritten adapter: only records the
source itself places in Suzhou are requested and published, dates come from explicit
``begin_time``/``end_time`` only, and a page without a verifiable SSR payload yields
an explicit failure instead of invented data.
"""
import json
from datetime import datetime, timezone

import httpx
import pytest

from backend.database import connect
from crawler.extractor import extract
from crawler.http import PublicClient
from crawler.pipeline import run_pipeline
from crawler.schema import CollectedItem
from crawler.sources.event_platform import huodongjia
from crawler.sources.event_platform.huodongjia import (
    HOME_URL,
    HuodongjiaSource,
    huodongjia_event,
    homepage_records,
)

HOST = 'https://www.huodongjia.com'
SUZHOU_URL = HOST + '/event-192901268450988032.html'
BEIJING_URL = HOST + '/event-801523941.html'
# A routable rules file for the adapter tests. The live site answers /robots.txt with a
# 200 HTML soft-404 (no directives at all), which this source opts into as "no usable
# rules" via accept_soft_404_robots; both the opt-in and the strict default are covered
# by dedicated tests below.
ROBOTS_ALLOW = 'User-agent: *\nAllow: /\n'


def detail_record(uuid='192901268450988032', **changes):
    record = {
        'event_uuid': uuid,
        'event_name': '2026 SAPA-China第六届医药产业大会',
        'event_type': None,
        'banner_url': 'https://huodongjiaimg.oss-cn-beijing.aliyuncs.com/eventcover/x.png',
        'seo_title': None,
        'seo_keywords': None,
        'seo_description': None,
        'begin_time': '2026-10-29 08:00:00',
        'end_time': '2026-10-30 17:00:00',
        'city_name': '苏州',
        'province_name': '江苏省',
        'venue_name': None,
        'price': {'min': 198, 'max': 198, 'currency': 'CNY', 'type': 'paid'},
        'tags': [{'id': 1214, 'tag_name': '医药'}],
        'categoryId': '1',
        'categorySlug': 'medical',
        'categoryName': '医疗医学',
        'organizer': {'name': '主办方', 'logo': ''},
        'status': 'selling',
        'description': '<p>主办单位： 郑州美中药协医药咨询有限公司（SAPA-China） 协办单位： 苏州浒墅关'
                       '经济技术开发区管理委员会 时间：10月29日-10月30日 地点：苏州狮山国际会议中心</p>'
                       '<p>由SAPA-China主办，苏州盛杰承办的“医药产业大会”将于2026年10月29日至30日'
                       '在苏州狮山国际会议中心隆重举行！</p>',
        'guests': [],
        'tickets': [{'id': '308186', 'name': '普通票', 'price': 198}],
    }
    record.update(changes)
    return record


def homepage_row(uuid='192901268450988032', name='2026 SAPA-China第六届医药产业大会',
                 begin='2026-10-29 08:00:00', city='苏州', province='江苏省'):
    return {'event_name': name, 'begin_time': begin, 'event_uuid': uuid,
            'min_price': 198, 'city_name': city, 'province_name': province, 'sort_order': 0}


def next_data(**page_props):
    return ('<!DOCTYPE html><html><head><title>活动家</title></head><body><div id="__next"></div>'
            '<script id="__NEXT_DATA__" type="application/json">'
            + json.dumps({'props': {'pageProps': page_props}}, ensure_ascii=False)
            + '</script></body></html>')


def homepage_payload(rows, group='it'):
    return next_data(initialData=[{'slug': group, 'cat_name': 'IT互联网', 'event_number': len(rows),
                                   'children': [{'slug': 'rengongzhineng', 'cat_name': '人工智能',
                                                 'event_number': len(rows), 'children': [],
                                                 'events': rows}],
                                   'events': []}],
                     initialBanners=[])


def detail_page(record=None):
    record = record or detail_record()
    return next_data(slug='event-' + str(record['event_uuid']) + '.html', pageType='event',
                     id=str(record['event_uuid']), seoData={'title': None}, initialData=record)


def plain_page(body='<p>活动家</p>'):
    return '<!DOCTYPE html><html><body>' + body + '</body></html>'


def client_for(handler):
    return PublicClient(transport=httpx.MockTransport(handler), interval=0, sleep=lambda n: None)


def rewritten_client(handler):
    """A source whose crawl URL was rewritten by the registry (the daily-run path)."""
    source = HuodongjiaSource(client=client_for(handler), max_items=5)
    source.crawl_url = 'https://www.huodongjia.com/suzhou/'
    return source


def record(raw, url=SUZHOU_URL, uuid='192901268450988032', extractor='huodongjia_ssr'):
    return CollectedItem(item_key='hdj-event-' + uuid, original_url=url, source_name='Huodongjia Suzhou',
                         crawl_time=datetime.now(timezone.utc), raw_content=raw,
                         extractor=extractor, locator=uuid)


class OneShot(HuodongjiaSource):
    """One collected detail item, no HTTP. Exercises the real pipeline path."""

    def __init__(self, raw=None, url=SUZHOU_URL, uuid='192901268450988032'):
        super().__init__(client=object(), max_items=1)
        self.raw = raw if raw is not None else detail_page(detail_record(uuid=uuid))
        self.url = url
        self.uuid = uuid

    def collect(self):
        return [record(self.raw, url=self.url, uuid=self.uuid)]


# --------------------------------------------------------------------------------------
# Pure extraction: explicit fields, provenance, never-Verified status
# --------------------------------------------------------------------------------------

def test_suzhou_detail_record_extracts_explicit_fields_and_full_provenance():
    event = huodongjia_event(record(detail_page()))
    assert event['event_name'] == '2026 SAPA-China第六届医药产业大会'
    assert event['start_date'] == '2026-10-29' and event['end_date'] == '2026-10-30'
    assert event['city'] == '苏州' and event['location'] == '苏州'
    assert event['venue'] == '苏州狮山国际会议中心'
    assert event['organizer'] == '郑州美中药协医药咨询有限公司(SAPA-China)'  # NFKC-normalised
    assert event['category'] == 'business' and event['venue_id'] is None and event['district_id'] is None
    assert event['source_url'] == SUZHOU_URL
    for field, claim in event['field_evidence'].items():
        assert 0 <= claim['confidence'] <= 1
        assert claim['status'] in ('Unverified', 'Missing', 'Needs Review')
        assert claim['status'] != 'Verified', field
        assert claim['method']
    assert 'begin_time=2026-10-29 08:00:00' in event['field_evidence']['start_date']['snippet']
    assert 'end_time=2026-10-30 17:00:00' in event['field_evidence']['end_date']['snippet']
    assert event['field_evidence']['source_url']['snippet'] == SUZHOU_URL
    assert event['field_evidence']['city']['method'].startswith('explicit_source_city')
    assert event['field_evidence']['venue']['status'] == 'Needs Review'
    assert event['field_evidence']['organizer']['status'] == 'Needs Review'


def test_platform_placeholder_organizer_is_never_published_as_a_name():
    event = huodongjia_event(record(detail_page(detail_record(description='<p>活动介绍</p>'))))
    assert event['organizer'] is None
    assert event['field_evidence']['organizer']['status'] == 'Missing'
    assert event['venue'] is None


def test_unlabelled_description_never_invents_venue_or_organizer():
    description = '<p>本届大会将汇聚全球产业领军人物，敬请期待。</p>'
    event = huodongjia_event(record(detail_page(detail_record(description=description))))
    assert event['venue'] is None and event['organizer'] is None
    assert event['location'] == '苏州'  # the source's own city field is the only location claim
    assert event['start_date'] == '2026-10-29'


@pytest.mark.parametrize('values', [
    {'begin_time': None, 'price': {'min': 198}, 'tickets': [{'name': '票', 'price': 198}]},
    {'begin_time': None, 'event_name': '2026医药产业大会'},
    {'begin_time': '2026-10-29 - 2026-10-30'},
    {'begin_time': '10-29'},
    {'begin_time': '2026-02-30 09:00:00'},
    {'end_time': '待定'},
    {'end_time': '2026-10-01 09:00:00'},
])
def test_missing_or_ambiguous_dates_are_rejected_without_substitution(values):
    with pytest.raises(ValueError):
        huodongjia_event(record(detail_page(detail_record(**values))))


@pytest.mark.parametrize('change', [
    {'city_name': '北京', 'province_name': '北京市'},
    {'city_name': '杭州', 'province_name': '浙江省'},
    {'city_name': None, 'province_name': '江苏省'},
    {'city_name': '苏州', 'province_name': '浙江省'},
    {'city_name': '苏州园区', 'province_name': '江苏省'},
])
def test_wrong_or_ambiguous_city_is_never_published(change):
    with pytest.raises(ValueError, match='Suzhou'):
        huodongjia_event(record(detail_page(detail_record(**change))))


def test_cancelled_status_is_not_published():
    with pytest.raises(ValueError, match='Cancelled'):
        huodongjia_event(record(detail_page(detail_record(status='cancelled'))))


def test_detail_uuid_must_match_the_requested_public_item():
    raw = detail_page(detail_record(uuid='801523941'))
    with pytest.raises(ValueError, match='does not match'):
        huodongjia_event(record(raw, url=SUZHOU_URL, uuid='192901268450988032'))


def test_payload_uuid_must_match_the_collected_locator():
    raw = detail_page(detail_record(uuid='801523941'))
    with pytest.raises(ValueError, match='does not match'):
        huodongjia_event(record(raw, url=BEIJING_URL, uuid='192901268450988032'))


def test_absent_next_data_is_an_explicit_failure_not_invented_data():
    shell = plain_page('<p>报名中 2026 SAPA-China第六届医药产业大会 2026-10-29 江苏省 苏州</p>')
    with pytest.raises(ValueError, match='__NEXT_DATA__'):
        huodongjia_event(record(shell))
    with pytest.raises(ValueError, match='__NEXT_DATA__'):
        homepage_records(shell)


def test_invalid_or_unsupported_payload_structure_fails_closed():
    with pytest.raises(ValueError, match='not valid JSON'):
        huodongjia_event(record('<script id="__NEXT_DATA__">{not json}</script>'))
    with pytest.raises(ValueError, match='no props.pageProps'):
        huodongjia_event(record('<script id="__NEXT_DATA__">{"props":{}}</script>'))
    with pytest.raises(ValueError, match='no event records'):
        homepage_records(next_data(initialData=[{'slug': 'it', 'children': []}]))
    with pytest.raises(ValueError, match='no category event groups'):
        homepage_records(next_data(initialData=[]))


@pytest.mark.parametrize('url', [
    'http://www.huodongjia.com/',
    'https://www.huodongjia.com:444/',
    'https://www.huodongjia.com/event-192901268450988032.html?token=x',
    'https://m.huodongjia.com/event-192901268450988032.html',
    'https://evil.test/event-192901268450988032.html',
    'https://www.huodongjia.com/event-192901268450988032',
    'https://www.huodongjia.com/suzhou/',
])
def test_only_approved_public_huodongjia_urls_are_collected(url):
    assert HuodongjiaSource.is_public_url(url) is False
    assert HuodongjiaSource.is_public_url(HOME_URL) is True
    assert HuodongjiaSource.is_public_url(SUZHOU_URL) is True


def test_blocked_page_is_retained_but_never_extracted():
    raw = detail_page().replace('<div id="__next"></div>', '<div>请先登录后查看</div>')
    with pytest.raises(ValueError, match='access wall'):
        huodongjia_event(record(raw))


# --------------------------------------------------------------------------------------
# Adapter collection: discovery, Suzhou-only filtering, max_items, stop conditions
# --------------------------------------------------------------------------------------

def test_homepage_ssr_discovery_fetches_only_suzhou_details(tmp_path):
    visited = []
    rows = [homepage_row(), homepage_row(uuid='801523941', name='AiCon北京2026',
                                         city='北京', province='北京市')]

    def handler(request):
        visited.append(str(request.url))
        if request.url.path == '/robots.txt':
            return httpx.Response(200, text=ROBOTS_ALLOW)
        if request.url.path == '/':
            return httpx.Response(200, text=homepage_payload(rows), headers={'Content-Type': 'text/html'})
        assert request.url.path == '/event-192901268450988032.html'
        return httpx.Response(200, text=detail_page(), headers={'Content-Type': 'text/html'})

    source = HuodongjiaSource(client=client_for(handler), max_items=5)
    try:
        report = run_pipeline(tmp_path / 'hdj.sqlite3', [source], request_client=source.client)
        assert not [url for url in visited if '/suzhou' in url]
        assert BEIJING_URL not in visited and SUZHOU_URL in visited
        assert report['attempts'][0]['investigation']['wrong_city_records_rejected'] == 1
        assert report['attempts'][0]['investigation']['supplied_city_route_requests'] == 0
        assert report['attempts'][0]['investigation']['detail_pages_fetched'] == 1
    finally:
        source.client.close()


def test_max_items_bounds_detail_page_requests():
    visited = []
    rows = [homepage_row(uuid=str(1000 + i), name='苏州测试活动%d' % i) for i in range(4)]

    def handler(request):
        visited.append(str(request.url))
        if request.url.path == '/robots.txt':
            return httpx.Response(200, text=ROBOTS_ALLOW)
        if request.url.path == '/':
            return httpx.Response(200, text=homepage_payload(rows), headers={'Content-Type': 'text/html'})
        uuid = request.url.path[len('/event-'):-len('.html')]
        return httpx.Response(200, text=detail_page(detail_record(uuid=uuid, event_name='苏州测试活动')),
                              headers={'Content-Type': 'text/html'})

    source = HuodongjiaSource(client=client_for(handler), max_items=2)
    try:
        source.collect()
        assert [url for url in visited if '/event-' in url] == [HOST + '/event-1000.html',
                                                                HOST + '/event-1001.html']
        assert source.investigation['detail_pages_fetched'] == 2
    finally:
        source.client.close()


def test_no_suzhou_records_publishes_nothing_and_requests_no_detail_page(tmp_path):
    visited = []
    rows = [homepage_row(uuid='801523941', name='AiCon北京2026', city='北京', province='北京市')]

    def handler(request):
        visited.append(str(request.url))
        if request.url.path == '/robots.txt':
            return httpx.Response(200, text=ROBOTS_ALLOW)
        return httpx.Response(200, text=homepage_payload(rows), headers={'Content-Type': 'text/html'})

    source = HuodongjiaSource(client=client_for(handler), max_items=5)
    try:
        report = run_pipeline(tmp_path / 'hdj-none.sqlite3', [source], request_client=source.client)
        assert report['eventsProcessed'] == 0 and report['eventsStored'] == 0
        assert report['status'] == 'Failed'
        assert not [url for url in visited if '/event-' in url]
        assert any('none of them in Suzhou' in warning for warning in source.warnings)
    finally:
        source.client.close()


def test_soft_404_robots_html_is_no_usable_rules_for_this_host():
    """www.huodongjia.com publishes no robots.txt at all: the URL returns the Next.js
    catch-all HTML with zero directives. That is "no usable rules", so collection
    proceeds to the public homepage - and the city shell is still never requested."""
    visited = []
    home = homepage_payload([homepage_row()])

    def handler(request):
        visited.append(str(request.url))
        assert request.url.path in ('/robots.txt', '/')
        if request.url.path == '/robots.txt':
            return httpx.Response(200, text='<html>页面走丢了</html>',
                                  headers={'Content-Type': 'text/html'})
        return httpx.Response(200, text=home, headers={'Content-Type': 'text/html'})

    source = HuodongjiaSource(client=client_for(handler), max_items=5)
    try:
        source.collect()
        assert source.accept_soft_404_robots is True
        assert visited[0] == HOST + '/robots.txt'
        assert HOST + '/' in visited
        assert all('/suzhou' not in url for url in visited)
        assert source.pages_collected >= 1
    finally:
        source.client.close()


def test_soft_404_robots_html_still_stops_a_strict_source():
    """The fail-closed default is preserved for any handler that has not verified that
    its host publishes no robots policy."""
    visited = []

    def handler(request):
        visited.append(str(request.url))
        assert request.url.path == '/robots.txt'
        return httpx.Response(200, text='<html>页面走丢了</html>')

    class StrictSource(HuodongjiaSource):
        accept_soft_404_robots = False

    source = StrictSource(client=client_for(handler), max_items=5)
    try:
        items = source.collect()
        assert StrictSource.accept_soft_404_robots is False
        assert visited == [HOST + '/robots.txt']
        assert source.pages_collected == 0
        assert not [item for item in items if item.is_event]
        assert 'HTML/non-rules' in source.errors[0]['error']
    finally:
        source.client.close()


def test_registry_rewritten_crawl_url_never_collects_the_js_only_city_route():
    visited = []

    def handler(request):
        visited.append(str(request.url))
        if request.url.path == '/robots.txt':
            return httpx.Response(200, text=ROBOTS_ALLOW)
        if request.url.path == '/suzhou/':
            return httpx.Response(200, text=plain_page('<div id="app"></div>'),
                                  headers={'Content-Type': 'text/html'})
        if request.url.path == '/':
            return httpx.Response(200, text=homepage_payload([homepage_row()]),
                                  headers={'Content-Type': 'text/html'})
        return httpx.Response(200, text=detail_page(), headers={'Content-Type': 'text/html'})

    source = rewritten_client(handler)
    try:
        items = source.collect()
        assert '/suzhou/' not in ''.join(visited)
        assert source.warnings and 'not the server-rendered homepage' in source.warnings[0]
        assert [item.item_key for item in items if item.is_event] == ['hdj-event-192901268450988032']
    finally:
        source.client.close()


def test_homepage_without_ssr_records_fails_closed_with_an_explicit_reason():
    def handler(request):
        if request.url.path == '/robots.txt':
            return httpx.Response(200, text=ROBOTS_ALLOW)
        return httpx.Response(200, text=plain_page('<p>活动家首页</p>'), headers={'Content-Type': 'text/html'})

    source = HuodongjiaSource(client=client_for(handler), max_items=5)
    try:
        items = source.collect()
        # robots policy text and the homepage context are retained; no event is invented.
        assert not [item for item in items if item.is_event]
        assert any(item.item_key == 'hdj-home' for item in items)
        assert any('__NEXT_DATA__' in error['error'] for error in source.errors)
    finally:
        source.client.close()


def test_anchor_links_are_a_bounded_fallback_when_the_payload_has_no_records():
    html = plain_page('<a href="/event-192901268450988032.html">苏州活动</a>'
                      '<a href="https://evil.test/event-999.html">外部</a>'
                      '<a href="/event-192901268450988032.html?token=x">带参</a>')
    assert huodongjia.anchor_candidates(html) == ['192901268450988032']


def test_nested_groups_are_walked_and_repeated_events_are_deduplicated():
    """The live payload repeats the same events across category groups."""
    suzhou = homepage_row()
    beijing = homepage_row(uuid='801523941', name='AiCon北京2026', city='北京', province='北京市')
    whole = next_data(initialData=[
        {'slug': 'it', 'cat_name': 'IT互联网', 'events': [beijing],
         'children': [{'slug': 'rengongzhineng', 'cat_name': '人工智能', 'events': [beijing, suzhou],
                       'children': [{'slug': 'deep', 'cat_name': '深度学习', 'events': [suzhou],
                                     'children': []}]}]},
        {'slug': 'medical', 'cat_name': '医疗医学', 'events': [suzhou],
         'children': [{'slug': 'yiyao', 'cat_name': '医药', 'events': [beijing], 'children': []}]},
    ], initialBanners=[])
    records = homepage_records(whole)
    assert [row['event_uuid'] for row in records] == ['801523941', '192901268450988032']
    assert sum(1 for row in records if row['city_name'] == '苏州') == 1


def test_the_whole_tree_is_walked_at_any_depth_without_truncation():
    """Discovery must not depend on how deep the payload nests its event lists."""
    suzhou = homepage_row()
    deep = suzhou
    for level in range(60):  # far past any recursion limit for a naive recursive walk
        deep = {'slug': 'level-%d' % level, 'children': [deep], 'events': []}
    whole = next_data(initialData=[
        {'slug': 'it', 'cat_name': 'IT互联网', 'events': [],
         'children': [{'slug': 'a', 'events': [homepage_row(uuid='801523941', name='AiCon北京2026',
                                                            city='北京', province='北京市')],
                       'children': []}]},
        deep,
    ], initialBanners=[])
    records = homepage_records(whole)
    assert [row['event_uuid'] for row in records] == ['801523941', '192901268450988032']


def test_live_payload_shape_is_fully_discovered(monkeypatch):
    """66 event objects collapsing to 21 distinct events were all visited on 2026-10-13."""
    rows = [homepage_row(uuid=str(1000 + i), name='苏州活动%d' % i) for i in range(3)]
    groups = [{'slug': 'g%d' % g, 'cat_name': '组%d' % g, 'events': rows,
               'children': [{'slug': 'c', 'events': list(reversed(rows)), 'children': []}]}
              for g in range(4)]
    records = homepage_records(next_data(initialData=groups, initialBanners=[]))
    assert len(records) == 3  # 24 event objects, 3 distinct events
    assert len({row['event_uuid'] for row in records}) == 3


# --------------------------------------------------------------------------------------
# End-to-end through the shared extractor/validator/pipeline contract
# --------------------------------------------------------------------------------------

def test_shared_extractor_dispatch_and_pipeline_publish_one_unified_event(tmp_path):
    event = extract(record(detail_page()), 'event_platform')
    assert event['city'] == '苏州' and event['start_date'] == '2026-10-29'
    assert event['venue'] == '苏州狮山国际会议中心'
    db = tmp_path / 'hdj-extract.sqlite3'
    report = run_pipeline(db, [OneShot()])
    assert report['eventsProcessed'] == 1 and report['eventsCreated'] == 1
    assert report['eventsStored'] == 1
    assert report['evidenceRecordsGenerated'] == len(event['field_evidence']) == 11
    with connect(db) as con:
        assert not con.execute('PRAGMA foreign_key_check').fetchall()
        raw = con.execute("SELECT * FROM crawler_raw_items WHERE validation_status='Published'").fetchone()
        assert raw['original_url'] == SUZHOU_URL and raw['raw_content'] == detail_page()
        evidence = con.execute('SELECT * FROM crawler_evidence').fetchall()
        assert {row['field_name'] for row in evidence} >= {'event_name', 'start_date', 'end_date',
                                                           'city', 'venue', 'organizer', 'source_url'}
        assert all(row['source_url'] == SUZHOU_URL for row in evidence)
        assert all(row['verification_status'] != 'Verified' for row in evidence)
