"""Priority-source checks use synthetic fixtures, never live Damai access."""
from datetime import datetime, timezone
import json
from pathlib import Path

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

from backend.database import connect, snapshot
from backend.main import create_app
from crawler.extractor import extract
from crawler.http import PublicClient
from crawler.pipeline import run_pipeline
from crawler.registry import REGISTRY_PATH, load_registry
from crawler.schema import CollectedItem
from crawler.sources.event_platform.damai import DamaiSource
from crawler.sources.event_platform.huodongjia import HuodongjiaSource
from crawler.sources.venue.expo import ExpoVenueSource

DETAIL = 'https://detail.damai.cn/item.htm?id=123456789012'
OTHER = 'https://detail.damai.cn/item.htm?id=123456789013'

# Minimal Huodongjia homepage SSR shape: props.pageProps.initialData is a list of
# category groups whose nested ``events`` entries carry the source's own city fields.
HOME_SSR = (
    '<html><head><title>活动家</title></head><body>'
    '<script id="__NEXT_DATA__" type="application/json">'
    + json.dumps({
        'props': {'pageProps': {'initialData': [{
            'slug': 'medical', 'cat_name': '医疗医学', 'event_number': 1,
            'children': [], 'events': [{
                'event_name': '2026 SAPA-China第六届医药产业大会',
                'begin_time': '2026-10-29 08:00:00',
                'city_name': '苏州', 'province_name': '江苏省',
                'event_uuid': '192901268450988032',
            }],
        }]}},
        'page': '/', 'query': {},
    }, ensure_ascii=False)
    + '</script></body></html>'
)


def event_node():
    return {'@type': 'MusicEvent', 'name': '苏州测试音乐会',
            'startDate': '2026-11-18T19:30:00+08:00',
            'location': {'name': '苏州文化艺术中心·大剧院',
                         'address': {'addressLocality': '苏州市', 'streetAddress': '苏州测试路1号'}}}


def html(node=None):
    return '<script type="application/ld+json">' + json.dumps(node or event_node(), ensure_ascii=False) + '</script>'


def record(raw):
    return CollectedItem(item_key='123456789012', original_url=DETAIL, source_name='Damai Suzhou',
                         crawl_time=datetime.now(timezone.utc), raw_content=raw,
                         extractor='damai_public_event')


def client_for(handler):
    return PublicClient(transport=httpx.MockTransport(handler), interval=0, sleep=lambda n: None)


def test_dedicated_adapter_allowed_detail_roundtrip_includes_city_evidence(tmp_path):
    visited = []

    def handler(request):
        visited.append(str(request.url))
        if request.url.path == '/robots.txt':
            return httpx.Response(200, text='User-agent: *\nDisallow: /' if request.url.host == 'search.damai.cn' else 'User-agent: *\nAllow: /item.htm')
        assert request.url.host == 'detail.damai.cn' and request.url.path == '/item.htm'
        return httpx.Response(200, text=html(), headers={'Content-Type': 'text/html'})

    client = client_for(handler)
    db = tmp_path / 'damai.sqlite3'
    try:
        source = DamaiSource(client=client)
        source.detail_urls = [DETAIL]
        report = run_pipeline(db, [source], request_client=client)
        assert report['eventsStored'] == report['eventsProcessed'] == 1
        assert report['evidenceRecordsGenerated'] == 11
        assert 'https://search.damai.cn/' not in visited
        with TestClient(create_app(db)) as api:
            event = api.get('/events').json()[0]
            assert event['name'] == '苏州测试音乐会' and event['city'] == '苏州'
            assert event['category'] == 'culture' and event['startDate'] == '2026-11-18'
            assert event['venueName'] == '苏州文化艺术中心·大剧院' and event['sourceUrl'] == DETAIL
            evidence = api.get('/evidence', params={'event_id': event['id']}).json()
            city = next(e for e in evidence if e['field'] == 'city')
            assert city['value'] == '苏州' and '苏州市' in city['snippet']
            assert city['raw_item_id'] and city['status'] == 'Unverified'
            assert all(0 <= e['confidence'] <= 1 and e['status'] != 'Verified' for e in evidence)
        with connect(db) as con:
            raw = con.execute("SELECT * FROM crawler_raw_items WHERE validation_status='Published'").fetchone()
            assert raw['raw_content'] == html() and raw['original_url'] == DETAIL and raw['crawl_time']
            assert not con.execute('PRAGMA foreign_key_check').fetchall()
    finally:
        client.close()


def test_robots_denial_never_requests_any_damai_body(tmp_path):
    visited = []

    def handler(request):
        visited.append(str(request.url))
        assert request.url.path == '/robots.txt'
        return httpx.Response(200, text='User-agent: *\nDisallow: /')

    client = client_for(handler)
    try:
        source = DamaiSource(client=client)
        source.detail_urls = [DETAIL, OTHER]
        report = run_pipeline(tmp_path / 'denied.sqlite3', [source], request_client=client)
        assert report['status'] == 'Failed' and report['eventsStored'] == 0
        assert report['pagesCollected'] == report['evidenceRecordsGenerated'] == 0
        assert len(visited) == 2 and all(u.endswith('/robots.txt') for u in visited)
        assert report['rawRecordsCollected'] == 2  # Policy text, never an event body.
    finally:
        client.close()


@pytest.mark.parametrize('status,body,headers', [
    (200, '<html>Oops 页面走丢了</html>', {}),
    (302, 'redirect', {'Location': 'https://detail.damai.cn/login'}),
    (403, 'denied', {}),
])
def test_unusable_detail_robots_stops_before_body_or_redirect(tmp_path, status, body, headers):
    visited = []

    def handler(request):
        visited.append(str(request.url))
        assert request.url.path == '/robots.txt'
        if request.url.host == 'search.damai.cn':
            return httpx.Response(200, text='User-agent: *\nDisallow: /')
        return httpx.Response(status, text=body, headers=headers)

    client = client_for(handler)
    try:
        source = DamaiSource(client=client)
        source.detail_urls = [DETAIL]
        report = run_pipeline(tmp_path / 'policy.sqlite3', [source], request_client=client)
        assert report['eventsProcessed'] == 0 and report['pagesCollected'] == 0
        assert len(visited) == 2 and all(u.endswith('/robots.txt') for u in visited)
        assert 'Robots policy unavailable' in report['attempts'][0]['error']
    finally:
        client.close()


def test_detail_redirect_to_login_is_rejected_without_target_request(tmp_path):
    visited = []

    def handler(request):
        visited.append(str(request.url))
        if request.url.path == '/robots.txt':
            return httpx.Response(404)
        if request.url.host == 'search.damai.cn':
            return httpx.Response(200, text='Public entry', headers={'Content-Type': 'text/html'})
        assert request.url.path == '/item.htm'
        return httpx.Response(302, headers={'Location': '/login'})

    client = client_for(handler)
    try:
        source = DamaiSource(client=client)
        source.detail_urls = [DETAIL]
        report = run_pipeline(tmp_path / 'redirect.sqlite3', [source], request_client=client)
        assert report['eventsStored'] == 0
        assert all('/login' not in url for url in visited)
        assert 'approved public page routes' in report['attempts'][0]['error']
    finally:
        client.close()


def test_captcha_stops_further_details_and_retains_rejected_raw(tmp_path):
    visited = []

    def handler(request):
        visited.append(str(request.url))
        if request.url.path == '/robots.txt':
            return httpx.Response(200, text='User-agent: *\nDisallow: /' if request.url.host == 'search.damai.cn' else 'User-agent: *\nAllow: /')
        return httpx.Response(200, text='<p>拖动滑块完成验证</p>' + html(), headers={'Content-Type': 'text/html'})

    client = client_for(handler)
    db = tmp_path / 'captcha.sqlite3'
    try:
        source = DamaiSource(client=client)
        source.detail_urls = [DETAIL, OTHER]
        report = run_pipeline(db, [source], request_client=client)
        assert report['eventsStored'] == 0 and OTHER not in visited
        with connect(db) as con:
            row = con.execute("SELECT * FROM crawler_raw_items WHERE validation_status='Rejected'").fetchone()
            assert row and '拖动滑块' in row['raw_content']
    finally:
        client.close()


@pytest.mark.parametrize('change', ['sale_only', 'missing_venue', 'missing_city', 'wrong_city', 'cancelled', 'postponed', 'ambiguous_dates', 'invalid_date'])
def test_incomplete_or_uncertain_event_data_is_not_published(change):
    node = event_node()
    if change == 'sale_only':
        node.pop('startDate'); node['sellStartTime'] = '2026-11-01'
    elif change == 'missing_venue':
        node['location'].pop('name')
    elif change == 'missing_city':
        node['location']['address'].pop('addressLocality')
    elif change == 'wrong_city':
        node['location']['address']['addressLocality'] = '上海市'
    elif change in ('cancelled', 'postponed'):
        node['eventStatus'] = 'https://schema.org/Event' + change.title()
    elif change == 'ambiguous_dates':
        node['startDate'] = '2026-11-18 - 2026-11-19'
    else:
        node['startDate'] = '2026-02-30'
    with pytest.raises(ValueError):
        extract(record(html(node)), 'event_platform')


def test_multiple_events_and_untyped_private_state_are_not_guessed():
    with pytest.raises(ValueError, match='one complete'):
        extract(record(html([event_node(), event_node()])), 'event_platform')
    raw = '<script>window.itemData=' + json.dumps(event_node()) + '</script>'
    with pytest.raises(ValueError, match='no API fallback'):
        extract(record(raw), 'event_platform')


@pytest.mark.parametrize('url', ['http://detail.damai.cn/item.htm?id=123456789012',
                                  'https://detail.damai.cn/item.htm?id=123456789012&token=x',
                                  'https://detail.damai.cn/api/item?id=123456789012',
                                  'https://m.damai.cn/item.htm?id=123456789012',
                                  'https://detail.damai.cn:444/item.htm?id=123456789012'])
def test_registry_rejects_noncanonical_or_protected_detail_seed(tmp_path, url):
    data = yaml.safe_load(REGISTRY_PATH.read_text(encoding='utf-8'))
    next(r for r in data['sources'] if r['adapter'] == 'damai')['detail_urls'] = [url]
    path = tmp_path / 'registry.yaml'; path.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError):
        load_registry(path)


def test_huodongjia_html_robots_is_an_explicit_verification_limit(tmp_path):
    """A host that publishes no robots rules at all: no page is requested if the
    source has not opted into the documented soft-404 ("no usable rules") semantics."""
    visited = []

    def handler(request):
        visited.append(str(request.url)); assert request.url.path == '/robots.txt'
        return httpx.Response(200, text='<html>页面走丢了</html>')

    class StrictSource(HuodongjiaSource):
        accept_soft_404_robots = False

    client = client_for(handler)
    try:
        report = run_pipeline(tmp_path / 'huo.sqlite3', [StrictSource(client=client)], request_client=client)
        assert report['status'] == 'Failed' and report['eventsStored'] == 0
        assert len(visited) == 1 and report['pagesCollected'] == 0
        assert 'HTML/non-rules' in report['attempts'][0]['error']
    finally:
        client.close()


def test_huodongjia_html_robots_soft_404_allows_the_server_rendered_homepage(tmp_path):
    """The verified production behaviour: /robots.txt serves the Next.js catch-all HTML
    with zero directives, so it means "no usable rules" and the public homepage is fetched."""
    visited = []

    def handler(request):
        visited.append(str(request.url))
        if request.url.path == '/robots.txt':
            return httpx.Response(200, text='<!DOCTYPE html><html><head><title>活动家</title></head></html>',
                                  headers={'Content-Type': 'text/html'})
        assert request.url.path == '/'
        return httpx.Response(200, text=HOME_SSR, headers={'Content-Type': 'text/html'})

    client = client_for(handler)
    try:
        source = HuodongjiaSource(client=client)
        assert source.accept_soft_404_robots is True
        items = source.collect()
        assert visited[0].endswith('/robots.txt') and 'https://www.huodongjia.com/' in visited
        assert any(not i.is_event for i in items)
    finally:
        client.close()


def test_huodongjia_genuine_robots_denial_still_stops_the_host(tmp_path):
    """A real denial (HTTP 403) must remain a hard stop even with the soft-404 opt-in."""
    visited = []

    def handler(request):
        visited.append(str(request.url))
        return httpx.Response(403, text='Forbidden')

    client = client_for(handler)
    try:
        report = run_pipeline(tmp_path / 'huo403.sqlite3', [HuodongjiaSource(client=client)], request_client=client)
        assert report['eventsStored'] == 0 and report['pagesCollected'] == 0
        assert len(visited) == 1
    finally:
        client.close()


def test_expo_retains_templates_and_detects_tokens_without_calling_api(tmp_path):
    visited = []
    raw = '<div v-for="item in list">{{item.name}}</div><a>2018</a><script>$.ajax({headers:{token:exampleToken}})</script>'

    def handler(request):
        visited.append(str(request.url))
        if request.url.path == '/robots.txt':
            return httpx.Response(404)
        assert request.url.path in ('/index.aspx', '/zhanhuiricheng-389.html')
        return httpx.Response(200, text=raw, headers={'Content-Type': 'text/html'})

    client = client_for(handler)
    try:
        report = run_pipeline(tmp_path / 'expo.sqlite3', [ExpoVenueSource(client=client)], request_client=client)
        assert report['status'] == 'Failed' and report['eventsStored'] == 0
        audit = report['attempts'][0]['investigation']
        assert audit['protected_api_requests'] == 0
        assert audit['token_header_detected'] and audit['template_placeholders_detected']
        assert report['pagesCollected'] == 2 and all('/api' not in u for u in visited)
    finally:
        client.close()


def test_failed_refresh_keeps_previous_city_evidence(tmp_path):
    blocked = False

    def handler(request):
        if request.url.path == '/robots.txt':
            if blocked or request.url.host == 'search.damai.cn':
                return httpx.Response(200, text='User-agent: *\nDisallow: /')
            return httpx.Response(404)
        return httpx.Response(200, text=html(), headers={'Content-Type': 'text/html'})

    client = client_for(handler); db = tmp_path / 'refresh.sqlite3'
    try:
        source = DamaiSource(client=client); source.detail_urls = [DETAIL]
        run_pipeline(db, [source]); before = snapshot(db)
        blocked = True
        source = DamaiSource(client=client); source.detail_urls = [DETAIL]
        report = run_pipeline(db, [source])
        assert report['status'] == 'Failed'
        assert snapshot(db)['events'] == before['events']
        assert snapshot(db)['evidence'] == before['evidence']
    finally:
        client.close()


def test_explicit_utc_event_time_uses_suzhou_calendar_date():
    node = event_node()
    node['startDate'] = '2026-11-18T20:30:00Z'
    event = extract(record(html(node)), 'event_platform')
    assert event['start_date'] == '2026-11-19'
    assert '20:30:00Z' in event['field_evidence']['start_date']['snippet']


def test_unrelated_recommendation_event_cannot_replace_requested_item():
    node = event_node()
    node['url'] = OTHER
    with pytest.raises(ValueError, match='does not match'):
        extract(record(html(node)), 'event_platform')


def test_robots_redirect_to_another_port_is_rejected():
    """A same-host robots redirect must not move collection to a different port."""

    def handler(request):
        if request.url.path == '/robots.txt':
            return httpx.Response(302, headers={'Location': 'https://www.example.test:444/robots.txt'})
        return httpx.Response(200, text='<html>page</html>', headers={'Content-Type': 'text/html'})

    client = PublicClient(transport=httpx.MockTransport(handler), interval=0)
    try:
        with pytest.raises(RuntimeError, match='leaves configured host'):
            client.get('https://www.example.test/events')
    finally:
        client.close()


def test_robots_redirect_keeping_the_same_https_port_is_followed():
    """A same-host, same-port robots redirect stays within the configured origin."""
    seen = []

    def handler(request):
        seen.append(str(request.url))
        if request.url.path == '/robots.txt' and request.url.port == 443:
            return httpx.Response(302, headers={'Location': '/robots.txt?v=2'})
        if request.url.path == '/robots.txt':
            return httpx.Response(200, text='User-agent: *\nDisallow: /private')
        return httpx.Response(200, text='<html>event</html>', headers={'Content-Type': 'text/html'})

    client = PublicClient(transport=httpx.MockTransport(handler), interval=0)
    try:
        page = client.get('https://www.example.test/events')
        assert page.content == '<html>event</html>'
        assert all('www.example.test:444' not in url for url in seen)
    finally:
        client.close()

