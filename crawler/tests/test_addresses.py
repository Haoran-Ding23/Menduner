"""Venue addresses: the source's place line is reduced to the address it actually carries.

Every string below is a real one from the live database (2026-10-15). The claim itself is never
rewritten — an event's ``location`` field keeps the whole source line with its own evidence; what
these checks pin is the *derived* venue-row address, which a human reads on the coordinate
maintenance screen and which the address resolver queries AMap with.
"""
import json

import httpx
import pytest

from backend.database import connect
from crawler.addresses import lookup_address, road_number, street_address, venue_address
from crawler.http import PublicClient
from crawler.pipeline import run_pipeline
from crawler.sources.venue.sscac import SscacVenueSource

# The example that started this: 豆瓣同城 writes city / district / venue / street as four tokens,
# and the old row stored all four as the address.
DOUBAN_PLACE = '苏州 吴中区 山丘livehouse-斜塘店 松涛街1088号斜塘老街36幢'
VISITSZ_PLACE = '苏州市吴中区东苑路1号苏州保利大剧院大剧场'


def test_the_reported_case_reduces_to_its_street_part():
    assert street_address(DOUBAN_PLACE, venue_name='山丘livehouse-斜塘店') == '松涛街1088号斜塘老街36幢'
    # ...and the lookup form stops at the house number.
    assert lookup_address(DOUBAN_PLACE) == '松涛街1088号'


def test_a_run_on_place_line_loses_its_administrative_prefix_and_repeated_name():
    assert street_address(VISITSZ_PLACE, venue_name='苏州保利大剧院') == '东苑路1号'
    assert street_address('苏州市工业园区中新大道东999号苏州奥林匹克体育中心体育馆',
                           venue_name='苏州奥林匹克体育中心体育馆') == '中新大道东999号'
    assert street_address('太仓市半泾南路3号太仓美术馆',
                          venue_name='太仓美术馆') == '半泾南路3号'
    assert street_address('昆山市巴城镇并蒂莲路2号昆山戏曲百戏博物馆',
                          venue_name='昆山戏曲百戏博物馆') == '并蒂莲路2号'


def test_a_venue_name_written_with_the_city_does_not_leave_the_city_behind():
    """The live 开明大戏院 row: the address repeats the name as 苏州开明大戏院."""
    assert street_address('苏州市姑苏区观前街北局11号苏州开明大戏院大剧场',
                          venue_name='开明大戏院') == '观前街北局11号'
    assert street_address('苏州 姑苏区 苏州开明大戏院 观前街北局11号',
                          venue_name='苏州开明大戏院') == '观前街北局11号'


def test_kept_detail_is_not_over_trimmed():
    """A hall inside the venue, a lane inside a 街道 and a parenthetical all stay readable."""
    assert street_address('苏州 吴中区 苏艺大珍珠魔术剧场 观枫街1号苏艺演艺文化集聚区3层8号魔术剧场',
                           venue_name='苏艺大珍珠魔术剧场') == '观枫街1号苏艺演艺文化集聚区3层8号魔术剧场'
    assert street_address('苏州 姑苏区 长歌演艺空间 平江街道皮市街9-69号(开元里2楼)',
                          venue_name='长歌演艺空间') == '平江街道皮市街9-69号(开元里2楼)'
    assert street_address('苏州 姑苏区 嘻哈壹笑堂相声茶馆 平江街道大儒巷38号(近长发商场)',
                          venue_name='嘻哈壹笑堂相声茶馆') == '平江街道大儒巷38号(近长发商场)'


def test_a_place_line_without_a_house_number_publishes_no_address():
    """A scenic area, a bare venue name and a metro-station street are not addresses."""
    for value in ('苏州工业园区李公堤文化创意街区',
                  '苏州国际博览中心',
                  '苏州 虎丘区 众戏剧文化艺术空间 长江路狮山文化广场B1众戏剧文化艺术空间',
                  '苏州 吴中区 苏州聚橙尹山湖大剧院',
                  '苏州奥体中心体育馆(部分图片源于网络,若有侵权请联系删除!)',
                  '国家5A级景区苏州工业园区金鸡湖景区',
                  '苏州'):
        assert street_address(value) is None, value
        assert lookup_address(value) is None, value


def test_lookup_reduces_a_spaced_place_line_even_without_a_venue_name():
    assert lookup_address('苏州 虎丘区 山丘livehouse-红唐店 滨河路999号喜年生活广场西侧一楼') == '滨河路999号'
    assert lookup_address('苏州 姑苏区 丝筵·丝路行歌全景沉浸式歌舞餐秀 平江街道人民路1755号13、15号楼丝筵') == \
        '平江街道人民路1755号'
    assert road_number('引黛街9号') == '引黛街9号'


def test_an_address_is_never_invented_from_the_venue_name():
    assert venue_address(None, 'X') is None
    assert venue_address('', 'X') is None
    assert venue_address('山丘livehouse-斜塘店', '山丘livehouse-斜塘店') is None
    # An address that is nothing but the venue's own name is not an address.
    assert street_address('苏州国际博览中心', venue_name='苏州国际博览中心') is None


def test_a_previously_published_address_is_not_rewritten_on_an_unchanged_claim(tmp_path):
    """The pipeline derives the address only for a row it creates; the claim stays untouched."""
    raw = {
        'code': 0, 'msg': 'ok',
        'obj': {'total': 1, 'size': 100, 'current': 1, 'pages': 1, 'records': [{
            'id': '1', 'deleted': 0,
            'projectName': '测试演出(主办)',
            'projectStartTime': '2027-05-01 19:30:00',
            'projectEndTime': '2027-05-01 21:30:00',
            'projectTypeId': '话剧',
            'siteName': '苏州文化艺术中心-大剧院',
            'projectCompany': '测试公司'}]}}
    html = ('<!DOCTYPE html><html><head><title>苏州文化艺术中心网站</title>'
            '<script src="/_nuxt/aaaaaaaaaaaaaaaa.js"></script>'
            '<script src="/_nuxt/bbbbbbbbbbbbbbbb.js"></script></head><body></body></html>')
    bundle = '"https://www.sscac.com.cn/sue/api"'

    def handler(request):
        if request.url.path == '/robots.txt':
            return httpx.Response(200, content=b'', headers={'Content-Type': 'text/plain'})
        if request.url.path == '/theatre-active':
            return httpx.Response(200, text=html, headers={'Content-Type': 'text/html'})
        if request.url.path.startswith('/_nuxt/'):
            return httpx.Response(200, text=bundle,
                                  headers={'Content-Type': 'application/javascript'})
        if request.url.path.endswith('findYanYiList'):
            return httpx.Response(200, json=raw, headers={'Content-Type': 'application/json'})
        return httpx.Response(200, json={'code': 0, 'obj': {'records': []}},
                              headers={'Content-Type': 'application/json'})

    db = tmp_path / 'address.sqlite3'
    client = PublicClient(transport=httpx.MockTransport(handler), interval=0,
                          sleep=lambda seconds: None)
    try:
        run_pipeline(db, [SscacVenueSource(client=client, max_items=5)], request_client=client)
    finally:
        client.close()
    with connect(db) as con:
        event = con.execute('SELECT payload FROM events').fetchone()
        venue = con.execute('SELECT payload FROM venues').fetchone()
        claim = con.execute("SELECT value FROM crawler_evidence WHERE field_name='location'"
                            ).fetchone()
    # The event keeps the location exactly as the source published it.
    assert json.loads(claim['value']) == '苏州文化艺术中心-大剧院'
    payload = json.loads(event['payload'])
    assert payload['venueName'] == '苏州文化艺术中心'
    assert json.loads(venue['payload'])['address'] is None  # a hall name is not an address
