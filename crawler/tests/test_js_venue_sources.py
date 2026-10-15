"""The two client-rendered venue sources: js-rendered calendars read through public JSON.

Both hosts serve an application shell with no event data in the HTML, and both publish the
calendar through the JSON endpoint their own JavaScript calls. These checks pin that contract
offline (MockTransport, never live access):

  * the endpoint route is discovered in the host's own published asset and never assumed;
  * the request shape and the static channel header come from the host's own page/config;
  * a page that stops advertising either one fails closed with no JSON request at all;
  * only explicit fields become claims, only the calendar date is published, and a finished
    or deleted record is skipped with a recorded reason instead of being republished.
"""
import json
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest

from crawler.http import PublicClient
from crawler.pipeline import run_pipeline
from crawler.registry import load_registry
from crawler.schema import CollectedItem
from crawler.sources.venue.expo import (
    ARTICLE_PATH,
    CATEGORY_PATH,
    CONFIG_PATH,
    HOST as EXPO_HOST,
    SCHEDULE_PATH,
    ExpoVenueSource,
    expo_exhibition,
    public_token,
    schedule_contract,
    year_categories,
)
from crawler.sources.venue.sscac import (
    DRAMA_PATH,
    HOST as ARTS_HOST,
    LISTING_PATH,
    YANYI_PATH,
    SscacVenueSource,
    local_today,
    sscac_performance,
)

EXPO_BASE = 'https://' + EXPO_HOST
ARTS_BASE = 'https://' + ARTS_HOST
TODAY = local_today()
FUTURE = (TODAY + timedelta(days=30)).isoformat()
FUTURE_END = (TODAY + timedelta(days=33)).isoformat()
PAST = (TODAY - timedelta(days=200)).isoformat()
PAST_END = (TODAY - timedelta(days=197)).isoformat()
EXPO_TOKEN = 'fyxmt'
EXPO_YEAR = TODAY.year

EXPO_SCHEDULE_HTML = (
    '<!DOCTYPE html><html><head><title>苏州国际博览中心_展会日程</title>'
    '<script src="/templates/expo_CN/js/config.js"></script></head><body>'
    '<div id="all"><li v-for="items in list"><p v-text="items.title"></p></li></div>'
    '<script>\n'
    '  var vm = new Vue({ methods: { init: function () {\n'
    '    $.ajax({ type: "GET", data: { cate_id: 389, is_sub: 0 },\n'
    '      url: config.host_url+"/api/Catogery/sub_list", dataType: "json",\n'
    '      headers: { "Access-Token": config.token } });\n'
    '    $.ajax({ type: "GET", data: { cate_id: lid, is_sub: true, albums:true, attachs:true,\n'
    '      pageIndex: 1, pageSize: 10000, sort: "start_time asc", search_params: "" },\n'
    '      url: config.host_url+"/api/Article/list", dataType: "json",\n'
    '      headers: { "Access-Token": config.token } });\n'
    '  } } });\n'
    '</script></body></html>'
)
EXPO_CONFIG_JS = ("var config = {\n  token: '" + EXPO_TOKEN + "',\n"
                  "  host_url: 'https://'+window.location.host\n};")


def expo_record(rid, title, start, end, organizer=''):
    return {'id': rid, 'title': title,
            'extras': {'start_time': start, 'end_time': end, 'organizer': organizer}}


EXPO_RECORDS = [
    expo_record(2079, '春节年货会', PAST + 'T15:57:01', PAST_END + 'T15:57:06'),
    expo_record(2149, 'NVIDIA会议', FUTURE + 'T14:41:49', FUTURE_END + 'T14:41:53'),
    expo_record(2152, '第35届中国厨师节暨2026中国厨师节博览会',
                (TODAY + timedelta(days=7)).isoformat() + 'T17:20:14',
                (TODAY + timedelta(days=9)).isoformat() + 'T17:20:17',
                organizer='中国烹饪协会'),
]


def expo_categories_payload():
    return {'success': True, 'code': 0, 'data': [
        {'id': 434, 'title': str(EXPO_YEAR)},
        {'id': 426, 'title': str(EXPO_YEAR - 1)},
        {'id': 424, 'title': str(EXPO_YEAR - 2)},
    ]}


def expo_articles_payload(records=None):
    return {'success': True, 'code': 0,
            'data': {'currentPage': 1, 'totalItems': len(records or EXPO_RECORDS),
                     'items': EXPO_RECORDS if records is None else records}}


def expo_client(visited, *, schedule=EXPO_SCHEDULE_HTML, config=EXPO_CONFIG_JS,
                categories=None, articles=None, calls=None):
    calls = calls if calls is not None else []

    def handler(request):
        visited.append(str(request.url))
        calls.append(request)
        if request.url.path == '/robots.txt':
            return httpx.Response(404)
        if request.url.path == SCHEDULE_PATH:
            return httpx.Response(200, text=schedule, headers={'Content-Type': 'text/html'})
        if request.url.path == CONFIG_PATH:
            return httpx.Response(200, text=config,
                                  headers={'Content-Type': 'application/javascript'})
        if request.url.path == CATEGORY_PATH:
            return httpx.Response(200, json=categories or expo_categories_payload())
        if request.url.path == ARTICLE_PATH:
            return httpx.Response(200, json=articles if articles is not None
                                  else expo_articles_payload())
        return httpx.Response(404)

    return PublicClient(transport=httpx.MockTransport(handler), interval=0,
                        sleep=lambda seconds: None)


# --------------------------------------------------------------------------------------
# Expo: the request contract comes from the host's own page and public config
# --------------------------------------------------------------------------------------

def test_schedule_contract_reads_the_pages_own_declaration():
    category_id, config_path = schedule_contract(EXPO_SCHEDULE_HTML)
    assert category_id == '389' and config_path == CONFIG_PATH
    assert schedule_contract('<html><body>no contract here</body></html>') == (None, None)


def test_public_token_is_read_from_the_hosts_own_config_file():
    assert public_token(EXPO_CONFIG_JS) == EXPO_TOKEN
    assert public_token('var config = { host_url: "x" };') is None


def test_only_the_current_and_next_year_categories_are_selected():
    document = {'success': True, 'data': [
        {'id': 1, 'title': str(TODAY.year + 1)},
        {'id': 2, 'title': str(TODAY.year)},
        {'id': 3, 'title': str(TODAY.year - 1)},
        {'id': 4, 'title': 'zhanlanricheng-2022'},
    ]}
    assert year_categories(document, TODAY) == [('1', TODAY.year + 1), ('2', TODAY.year)]
    # The live listing is ordered 2026, 2025, ...; a past year is never requested.
    assert [year for _, year in year_categories(expo_categories_payload(), TODAY)] == [EXPO_YEAR]


def test_expo_reads_the_public_json_its_own_page_declares(tmp_path):
    visited, calls = [], []
    client = expo_client(visited, calls=calls)
    try:
        report = run_pipeline(tmp_path / 'expo.sqlite3', [ExpoVenueSource(client=client)],
                              request_client=client)
    finally:
        client.close()
    assert report['attempts'][0]['status'] == 'Success'
    assert report['eventsStored'] == 2  # the finished 春节年货会 is never republished
    api_calls = [c for c in calls if c.url.path in (CATEGORY_PATH, ARTICLE_PATH)]
    assert api_calls, visited
    for call in api_calls:
        # The static channel token is the host's own published constant, read from config.js.
        assert call.headers.get('access-token') == EXPO_TOKEN
    article = [c for c in api_calls if c.url.path == ARTICLE_PATH][0]
    assert article.url.params['cate_id'] == '434'
    assert article.url.params['sort'] == 'start_time asc'
    investigation = report['attempts'][0]['investigation']
    assert investigation['credentials_used'] == 0
    assert investigation['records_seen'] == len(EXPO_RECORDS)
    assert [r['id'] for r in investigation['records_rejected']] == ['2079']
    assert 'finished before' in investigation['records_rejected'][0]['reason']


def test_expo_publishes_only_the_calendar_date_and_the_hosts_own_venue(tmp_path):
    from backend.database import connect
    db = tmp_path / 'expo-fields.sqlite3'
    visited = []
    client = expo_client(visited)
    try:
        run_pipeline(db, [ExpoVenueSource(client=client)], request_client=client)
    finally:
        client.close()
    with connect(db) as con:
        rows = {r['name']: r for r in con.execute('SELECT * FROM events')}
        venue = con.execute('SELECT * FROM venues WHERE id=(SELECT venue FROM events LIMIT 1)'
                            ).fetchone()
    assert set(rows) == {'第35届中国厨师节暨2026中国厨师节博览会', 'NVIDIA会议'}
    event = rows['NVIDIA会议']
    assert event['startDate'] == FUTURE and event['endDate'] == FUTURE_END
    assert event['category'] == 'business'
    assert venue['payload'].find('苏州国际博览中心') >= 0
    events = [json.loads(r['payload']) for r in rows.values()]
    assert all(e['demo'] == 0 for e in events)


def test_expo_fails_closed_when_the_page_stops_declaring_the_api(tmp_path):
    visited = []
    client = expo_client(visited, schedule='<html><head><title>苏州国际博览中心_展会日程</title>'
                                           '</head><body>no api here</body></html>')
    try:
        report = run_pipeline(tmp_path / 'expo-nocontract.sqlite3',
                              [ExpoVenueSource(client=client)], request_client=client)
    finally:
        client.close()
    assert report['attempts'][0]['status'] == 'Failed'
    assert report['eventsStored'] == 0
    assert not [u for u in visited if '/api/' in u], visited
    assert 'never assumed' in report['attempts'][0]['error']


def test_expo_fails_closed_when_the_public_config_publishes_no_token(tmp_path):
    visited = []
    client = expo_client(visited, config='var config = { host_url: "x" };')
    try:
        report = run_pipeline(tmp_path / 'expo-notoken.sqlite3',
                              [ExpoVenueSource(client=client)], request_client=client)
    finally:
        client.close()
    assert report['attempts'][0]['status'] == 'Failed'
    assert report['eventsStored'] == 0
    assert not [u for u in visited if '/api/' in u], visited
    assert 'channel token' in report['attempts'][0]['error']


def test_expo_fails_closed_when_the_host_identifies_as_another_venue(tmp_path):
    visited = []
    client = expo_client(visited, schedule=EXPO_SCHEDULE_HTML.replace(
        '<title>苏州国际博览中心_展会日程</title>', '<title>某展览公司</title>'))
    try:
        report = run_pipeline(tmp_path / 'expo-title.sqlite3', [ExpoVenueSource(client=client)],
                              request_client=client)
    finally:
        client.close()
    assert report['attempts'][0]['status'] == 'Failed' and report['eventsStored'] == 0
    assert 'identifies itself' in report['attempts'][0]['error']
    # Only robots + the page were requested; the title check happens before any JSON call.
    assert [u for u in visited if '/api/' in u] == []


def test_expo_reports_a_finished_year_archive_without_publishing_it(tmp_path):
    visited = []
    client = expo_client(visited, articles=expo_articles_payload(
        [expo_record(2079, '春节年货会', PAST + 'T15:57:01', PAST_END + 'T15:57:06')]))
    try:
        report = run_pipeline(tmp_path / 'expo-archive.sqlite3',
                              [ExpoVenueSource(client=client)], request_client=client)
    finally:
        client.close()
    assert report['eventsStored'] == 0
    assert report['attempts'][0]['status'] == 'Failed'
    assert 'No upcoming exhibition record' in report['attempts'][0]['error']
    assert report['attempts'][0]['contextRecords'] >= 1


def test_expo_extractor_rejects_a_mismatched_or_dateless_record():
    def item(raw, locator='2149'):
        return CollectedItem(item_key='expo-' + locator,
                             original_url=EXPO_BASE + ARTICLE_PATH,
                             source_name='苏州国际博览中心官方展会日程',
                             crawl_time=datetime.now(timezone.utc), raw_content=raw,
                             extractor='expo_exhibition', locator=locator)

    with pytest.raises(ValueError, match='does not match'):
        expo_exhibition(item(json.dumps(expo_record(2150, 'x', FUTURE, FUTURE_END))))
    with pytest.raises(ValueError, match='no complete YYYY-MM-DD'):
        expo_exhibition(item(json.dumps(expo_record(2149, 'x', '明天', '后天'))))
    with pytest.raises(ValueError, match='no title'):
        expo_exhibition(item(json.dumps(expo_record(2149, '', FUTURE, FUTURE_END))))
    event = expo_exhibition(item(json.dumps(expo_record(
        2149, 'NVIDIA会议', FUTURE + 'T14:41:49', FUTURE_END + 'T14:41:53'))))
    assert event['start_date'] == FUTURE
    assert 'CMS insertion time' in event['field_evidence']['start_date']['snippet']
    assert event['venue'] == '苏州国际博览中心'
    assert event['category'] == 'business'


# --------------------------------------------------------------------------------------
# Arts centre: the endpoint is discovered in the host's own published bundle
# --------------------------------------------------------------------------------------

BUNDLE_WITHOUT_API = 'window.__NUXT__={layout:"default"};'
BUNDLE_WITH_API = (
    'var h={a:{cpIds:[]}};this.$axios.post("/cinema/findYanYiList",{currentPage:0,pageSize:6});'
    'this.$axios.post("/cinema/showDramaInfoList",{startTime:"2026-01-01"});'
    'https://www.sscac.com.cn/sue/api'
)
ARTS_SHELL = (
    '<!DOCTYPE html><html><head><title>苏州文化艺术中心网站</title>'
    '<script src="/_nuxt/18fca92f8bb8a0d1cf66.js"></script>'
    '<script src="/_nuxt/b927a85950d9b531d776.js"></script>'
    '</head><body><div id="__nuxt"></div>'
    '<script>window.__NUXT__={state:{list:{list:[]}}}</script></body></html>'
)


def sscac_record(rid, name, start, end, site='苏州文化艺术中心-大剧院', ptype='音乐剧',
                 deleted=0, company='苏州文化艺术中心'):
    return {'id': rid, 'deleted': deleted, 'projectName': name, 'projectStartTime': start,
            'projectEndTime': end, 'projectTypeId': ptype, 'siteName': site,
            'projectCompany': company}


ARTS_YANYI = [
    sscac_record('240070048', '韩真、周莉亚新作 浙江演艺集团舞剧《栋梁》（主办）',
                 FUTURE + ' 19:30:00', FUTURE_END + ' 22:00:00', ptype='舞蹈'),
    sscac_record('240185001', '百老汇原版音乐剧《长靴皇后》（主办）',
                 (TODAY + timedelta(days=60)).isoformat() + ' 19:30:00',
                 (TODAY + timedelta(days=63)).isoformat() + ' 17:00:00'),
    sscac_record('238949020', '法语原版音乐剧《茶花女》（主办）',
                 PAST + ' 19:30:00', PAST_END + ' 22:00:00'),
]
ARTS_DRAMA = [
    sscac_record('240185001', '百老汇原版音乐剧《长靴皇后》（主办）',
                 (TODAY + timedelta(days=60)).isoformat() + ' 19:30:00',
                 (TODAY + timedelta(days=63)).isoformat() + ' 17:00:00'),
    sscac_record('240013002', '家学琴传  古琴世家联谊会专场音乐会',
                 (TODAY + timedelta(days=3)).isoformat() + ' 19:30:00',
                 (TODAY + timedelta(days=3)).isoformat() + ' 21:30:00',
                 site='苏州文化艺术中心-大道喜剧院', ptype='音乐'),
    sscac_record('240999999', '已删除的场次', FUTURE + ' 19:30:00', FUTURE + ' 21:00:00',
                 deleted=1),
]


def arts_envelope(records):
    return {'code': 0, 'msg': '操作成功',
            'obj': {'total': len(records), 'size': 100, 'current': 1, 'pages': 1,
                    'records': records}}


def arts_client(visited, *, shell=ARTS_SHELL, bundles=None, bodies=None):
    bundles = bundles if bundles is not None else {
        '/_nuxt/18fca92f8bb8a0d1cf66.js': BUNDLE_WITHOUT_API,
        '/_nuxt/b927a85950d9b531d776.js': BUNDLE_WITH_API,
    }
    bodies = bodies if bodies is not None else {'/cinema/findYanYiList': ARTS_YANYI,
                                                '/cinema/showDramaInfoList': ARTS_DRAMA}

    def handler(request):
        visited.append((request.method, str(request.url)))
        if request.url.path == '/robots.txt':
            return httpx.Response(200, content=b'',
                                  headers={'Content-Type': 'text/plain'})
        if request.url.path == LISTING_PATH:
            return httpx.Response(200, text=shell, headers={'Content-Type': 'text/html'})
        if request.url.path.startswith('/_nuxt/'):
            body = bundles.get(request.url.path)
            if body is None:
                return httpx.Response(404)
            return httpx.Response(200, text=body,
                                  headers={'Content-Type': 'application/javascript'})
        if request.url.path.startswith('/sue/api/'):
            records = bodies.get(request.url.path[len('/sue/api'):])
            if records is None:
                return httpx.Response(404)
            return httpx.Response(200, json=arts_envelope(records),
                                  headers={'Content-Type': 'application/json;charset=UTF-8'})
        return httpx.Response(404)

    return PublicClient(transport=httpx.MockTransport(handler), interval=0,
                        sleep=lambda seconds: None)


def arts_record_item(record, extractor='sscac_performance'):
    return CollectedItem(item_key='sscac-' + str(record['id']),
                         original_url=ARTS_BASE + YANYI_PATH,
                         source_name='Suzhou Culture and Arts Centre',
                         crawl_time=datetime.now(timezone.utc),
                         raw_content=json.dumps(record, ensure_ascii=False),
                         extractor=extractor, locator=str(record['id']))


def test_sscac_reads_the_json_endpoint_advertised_by_the_hosts_own_bundle(tmp_path):
    visited = []
    client = arts_client(visited)
    try:
        report = run_pipeline(tmp_path / 'arts.sqlite3', [SscacVenueSource(client=client)],
                              request_client=client)
    finally:
        client.close()
    assert report['attempts'][0]['status'] == 'Success'
    posts = [u for m, u in visited if m == 'POST']
    assert posts and all('/sue/api/cinema/' in u for u in posts), visited
    # Three upcoming performances survive; the finished 茶花女 and the deleted record do not.
    assert report['eventsStored'] == 3
    investigation = report['attempts'][0]['investigation']
    assert investigation['endpoint_discovered_in_published_bundle'] is True
    assert investigation['endpoint_bundle'].endswith('b927a85950d9b531d776.js')
    assert investigation['records_available'] == 3
    assert investigation['credentials_used'] == 0


def test_sscac_posts_the_filter_body_its_own_page_sends():
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path == '/robots.txt':
            return httpx.Response(200, content=b'', headers={'Content-Type': 'text/plain'})
        if request.url.path == LISTING_PATH:
            return httpx.Response(200, text=ARTS_SHELL, headers={'Content-Type': 'text/html'})
        if request.url.path == '/_nuxt/b927a85950d9b531d776.js':
            return httpx.Response(200, text=BUNDLE_WITH_API,
                                  headers={'Content-Type': 'application/javascript'})
        if request.url.path.startswith('/_nuxt/'):
            return httpx.Response(200, text=BUNDLE_WITHOUT_API,
                                  headers={'Content-Type': 'application/javascript'})
        records = ARTS_DRAMA if request.url.path == '/sue/api' + DRAMA_PATH else ARTS_YANYI
        return httpx.Response(200, json=arts_envelope(records),
                              headers={'Content-Type': 'application/json;charset=UTF-8'})

    client = PublicClient(transport=httpx.MockTransport(handler), interval=0,
                          sleep=lambda seconds: None)
    try:
        source = SscacVenueSource(client=client, max_items=40)
        source.collect()
    finally:
        client.close()
    bodies = {r.url.path: json.loads(r.content.decode()) for r in seen if r.method == 'POST'}
    yanyi = bodies[YANYI_PATH]
    drama = bodies[DRAMA_PATH]
    assert yanyi['status'] == '1' and yanyi['pageSize'] > 0
    assert yanyi['orders'] == [{'column': 'projectStartTime', 'sort': 'asc'}]
    assert 'startTime' not in yanyi  # the performance calendar needs no date filter
    # The 戏剧 endpoint answers its 1992..archive without this filter, so it is always sent.
    assert drama['startTime'] == local_today().isoformat()
    assert set(bodies) == {YANYI_PATH, DRAMA_PATH}


def test_sscac_fails_closed_when_no_published_bundle_advertises_the_api(tmp_path):
    visited = []
    client = arts_client(visited, bundles={'/_nuxt/18fca92f8bb8a0d1cf66.js': BUNDLE_WITHOUT_API,
                                           '/_nuxt/b927a85950d9b531d776.js': BUNDLE_WITHOUT_API})
    try:
        report = run_pipeline(tmp_path / 'arts-nobundle.sqlite3',
                              [SscacVenueSource(client=client)], request_client=client)
    finally:
        client.close()
    assert report['attempts'][0]['status'] == 'Failed'
    assert report['eventsStored'] == 0
    assert not [u for m, u in visited if m == 'POST'], visited
    assert 'never assumed' in report['attempts'][0]['error']


def test_sscac_fails_closed_when_the_page_is_not_the_venue(tmp_path):
    visited = []
    client = arts_client(visited, shell=ARTS_SHELL.replace(
        '<title>苏州文化艺术中心网站</title>', '<title>Some Other Site</title>'))
    try:
        report = run_pipeline(tmp_path / 'arts-title.sqlite3', [SscacVenueSource(client=client)],
                              request_client=client)
    finally:
        client.close()
    assert report['attempts'][0]['status'] == 'Failed' and report['eventsStored'] == 0
    assert 'identifies itself' in report['attempts'][0]['error']
    assert not [u for m, u in visited if m == 'POST'], visited


def test_sscac_extractor_publishes_only_explicit_fields():
    event = sscac_performance(arts_record_item(ARTS_YANYI[0]))
    # The shared text normaliser applies NFKC, so the source's full-width brackets are folded
    # exactly as every other adapter folds them; no other part of the name is touched.
    assert event['event_name'] == '韩真、周莉亚新作 浙江演艺集团舞剧《栋梁》(主办)'
    assert event['start_date'] == FUTURE and event['end_date'] == FUTURE_END
    assert event['venue'] == '苏州文化艺术中心'
    assert event['location'] == '苏州文化艺术中心-大剧院'
    assert event['category'] == 'culture'
    assert event['venue_id'] is None and event['district_id'] is None
    assert event['field_evidence']['start_date']['method'] == \
        'explicit_source_performance_start_datetime'
    assert event['field_evidence']['location']['method'].startswith(
        'explicit_source_siteName_field')
    assert event['field_evidence']['end_date']['snippet'].startswith('projectEndTime=')


def test_sscac_extractor_rejects_deleted_and_dateless_records():
    deleted = sscac_record('1', 'x', FUTURE + ' 19:30:00', FUTURE + ' 21:00:00', deleted=1)
    with pytest.raises(ValueError, match='deleted'):
        sscac_performance(arts_record_item(deleted))
    dateless = sscac_record('2', 'x', '待定', '待定')
    with pytest.raises(ValueError, match='no complete YYYY-MM-DD'):
        sscac_performance(arts_record_item(dateless))
    mismatched = CollectedItem(item_key='sscac-9', original_url=ARTS_BASE + YANYI_PATH,
                               source_name='Suzhou Culture and Arts Centre',
                               crawl_time=datetime.now(timezone.utc),
                               raw_content=json.dumps(ARTS_YANYI[0], ensure_ascii=False),
                               extractor='sscac_performance', locator='9')
    with pytest.raises(ValueError, match='does not match'):
        sscac_performance(mismatched)


def test_sscac_keeps_one_event_per_source_record_id_across_both_lists(tmp_path):
    """Both endpoints carry the same programme; the source's own id is the identity."""
    visited = []
    client = arts_client(visited)
    try:
        source = SscacVenueSource(client=client, max_items=40)
        items = [i for i in source.collect() if i.is_event]
    finally:
        client.close()
    keys = [i.item_key for i in items]
    assert len(keys) == len(set(keys))
    assert sorted(keys) == ['sscac-240013002', 'sscac-240070048', 'sscac-240185001']


# --------------------------------------------------------------------------------------
# The shared boundary: a public JSON request may never carry a credential
# --------------------------------------------------------------------------------------

def test_public_json_refuses_credential_headers_and_unapproved_methods():
    client = PublicClient()
    try:
        with pytest.raises(ValueError, match='credential'):
            client.request_json(EXPO_BASE + ARTICLE_PATH,
                                headers={'Authorization': 'Bearer not-allowed'})
        with pytest.raises(ValueError, match='credential'):
            client.request_json(EXPO_BASE + ARTICLE_PATH, headers={'Cookie': 'a=b'})
        with pytest.raises(ValueError, match='GET and POST'):
            client.request_json(EXPO_BASE + ARTICLE_PATH, method='DELETE')
        with pytest.raises(ValueError, match='requires POST'):
            client.request_json(EXPO_BASE + ARTICLE_PATH, json_body={'a': 1})
    finally:
        client.close()


def test_published_js_is_only_read_with_an_explicit_media_allow_list():
    """A JS asset is not a page: the default page contract refuses it, and the adapter asks
    for it explicitly instead of quietly widening what every other source may fetch."""
    def handler(request):
        if request.url.path == '/robots.txt':
            return httpx.Response(404)
        return httpx.Response(200, text='var config = {};',
                              headers={'Content-Type': 'application/javascript'})

    client = PublicClient(transport=httpx.MockTransport(handler), interval=0,
                          sleep=lambda seconds: None)
    try:
        with pytest.raises(ValueError, match='Unsupported page content type'):
            client.get(EXPO_BASE + CONFIG_PATH)
        page = client.get(EXPO_BASE + CONFIG_PATH, media=('javascript',))
    finally:
        client.close()
    assert 'token' not in page.content  # the fixture publishes no token, and none is invented


def test_both_rebuilt_sources_are_event_extractors_in_the_registry():
    definitions = {d.adapter: d for d in load_registry()}
    for adapter in ('arts', 'expo'):
        assert definitions[adapter].implementation == 'event_extraction', adapter
        assert definitions[adapter].require_events is not False, adapter
    assert definitions['arts'].crawl_url == ARTS_BASE + '/'
    assert definitions['expo'].crawl_url == EXPO_BASE + SCHEDULE_PATH


def test_registry_ledger_still_holds_a_source_that_cannot_publish(tmp_path):
    """The two rebuilt rows are no longer audit-only, but a real limitation stays recorded."""
    definitions = {d.adapter: d for d in load_registry()}
    assert definitions['expo'].limitation and 'config.js' in definitions['expo'].limitation
    assert definitions['arts'].limitation and 'sue/api' in definitions['arts'].limitation
    assert date.today() >= date(2026, 1, 1)  # the ledger's clock is the run's, not a fixture
