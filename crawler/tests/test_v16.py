"""V1.6 tests use synthetic HTML/JSON through MockTransport, never live requests."""
import json
from pathlib import Path
import sys

import httpx
import pytest
import yaml

from backend.database import connect, snapshot
from crawler.coverage import attach_coverage
from crawler.extractor import extract
from crawler.http import PublicClient
from crawler.pipeline import run_pipeline
from crawler.registry import CATEGORIES, REGISTRY_PATH, load_registry, tier1_keys
from crawler.schema import CollectedItem
from crawler.sources import SOURCES
from crawler.sources.cityevent import CultureTourismSource, OlympicSource
from crawler.tests.test_v15 import item


ARTICLE = '<div class="con_details"><h2>测试活动报道</h2><div class="text"><p>10月11日，2026苏州测试文化节在苏州测试展览馆举办。</p></div></div>'
OLYMPIC = ('<h2>测试苏州足球比赛</h2><div class="hdxx_ncen">'
           '<span>活动日期<font>2026-11-10 - 2026-11-12</font></span>'
           '<span>活动地点<font>苏州奥体中心体育场</font></span></div>')


def record(raw, host='wglj.suzhou.gov.cn', extractor='official_article_v16'):
    return item(raw, extractor).model_copy(update={'original_url': 'https://' + host + '/event'})


def copy_registry(tmp_path):
    path = tmp_path / 'registry.yaml'
    path.write_bytes(REGISTRY_PATH.read_bytes())
    return path


def test_registry_contains_all_tier1_sources_and_manual_wechat():
    definitions = load_registry()
    assert len(definitions) == len({d.source_id for d in definitions})
    assert len(tier1_keys()) == 10
    assert set(yaml.safe_load(REGISTRY_PATH.read_text(encoding='utf-8'))['categories']) == set(CATEGORIES)
    assert {d.adapter for d in definitions if d.adapter} == set(SOURCES)
    for d in definitions:
        if d.adapter:
            assert SOURCES[d.adapter](client=object()).source_id == d.source_id
    wechat = next(d for d in definitions if d.category == 'social_media')
    assert wechat.source_name == wechat.name == '苏州发布'
    assert wechat.platform == 'WeChat' and wechat.status == 'Manual verification required'
    assert wechat.adapter is None and wechat.implementation == 'manual_only'
    assert next(d for d in definitions if d.adapter == 'cnena').category == 'event_platform'


@pytest.mark.parametrize('change', ['duplicate', 'unknown_category', 'failed_without_reason', 'wechat_adapter'])
def test_registry_rejects_unsafe_or_ambiguous_records(tmp_path, change):
    path = copy_registry(tmp_path)
    data = yaml.safe_load(path.read_text(encoding='utf-8'))
    if change == 'duplicate':
        data['sources'][1]['source_id'] = data['sources'][0]['source_id']
    elif change == 'unknown_category':
        data['sources'][0]['category'] = 'exhibition'
    elif change == 'failed_without_reason':
        data['sources'][0].update(crawl_status='FAILED', reason=None)
    else:
        data['sources'][-1]['adapter'] = 'wechat'
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError):
        load_registry(path)


def test_official_body_date_uses_explicit_event_year_and_evidence():
    event = extract(record(ARTICLE), 'government')
    assert event['event_name'] == '2026苏州测试文化节'
    assert event['start_date'] == '2026-10-11' and event['end_date'] is None
    assert event['venue'] == '苏州测试展览馆' and event['organizer'] is None
    assert event['field_evidence']['start_date']['status'] == 'Needs Review'
    assert '10月11日' in event['field_evidence']['start_date']['snippet']
    assert all(c['status'] != 'Verified' for c in event['field_evidence'].values())


@pytest.mark.parametrize('raw', [
    ARTICLE.replace('10月11日，', '近日，'),
    ARTICLE.replace('2026苏州测试文化节', '苏州测试文化节'),
    ARTICLE.replace('10月11日，2026苏州测试文化节在苏州测试展览馆举办。',
                    '近日举行首演。2006年10月6日，该馆开放。'),
])
def test_publication_relative_and_historical_dates_do_not_create_events(raw):
    raw = '<meta name="PubDate" content="2026-10-13">' + raw
    with pytest.raises(ValueError):
        extract(record(raw), 'government')


def test_media_date_requires_explicit_single_event_context():
    raw = '<div class="msg-title"><div class="title-text">2026苏州测试音乐会</div></div><div id="arcBodyText"><p>2026年11月10日，2026苏州测试音乐会在苏州测试音乐厅上演。</p></div>'
    event = extract(record(raw, 'www.subaonet.com', 'media_article_v16'), 'media')
    assert event['start_date'] == '2026-11-10' and event['venue'] == '苏州测试音乐厅'
    with pytest.raises(ValueError):
        extract(record(raw.replace('2026年11月10日', '昨天'), 'www.subaonet.com', 'media_article_v16'), 'media')


def test_olympic_uses_event_labels_not_footer_or_copyright_year():
    raw = '<p>2010-2024 All Rights Reserved</p>' + OLYMPIC
    event = extract(record(raw, 'www.szosc.cn', 'olympic_detail'), 'venue')
    assert event['start_date'] == '2026-11-10' and event['end_date'] == '2026-11-12'
    assert event['category'] == 'sports' and event['venue'] == '苏州奥体中心体育场'
    assert event['organizer'] is None and event['district_id'] is None


def test_multi_venue_tournament_does_not_create_a_single_venue_reference():
    raw = OLYMPIC.replace('苏州奥体中心体育场', '苏州奥体中心体育场、训练场以及足球公园等场地')
    event = extract(record(raw, 'www.szosc.cn', 'olympic_detail'), 'venue')
    assert event['venue'] is None and '训练场' in event['location']
    assert event['field_evidence']['location']['status'] == 'Needs Review'


@pytest.mark.parametrize('raw', [OLYMPIC.replace('2026-11-10 - 2026-11-12', '待定'),
                                  OLYMPIC.replace('测试苏州足球比赛', '测试苏州足球比赛已取消'),
                                  OLYMPIC.replace('苏州奥体中心体育场', '上海体育场')])
def test_olympic_rejects_ambiguous_dates_cancelled_events_and_wrong_city(raw):
    with pytest.raises(ValueError):
        extract(record(raw, 'www.szosc.cn', 'olympic_detail'), 'venue')


def test_official_listing_has_bounded_details_and_ignores_external_links(tmp_path):
    visited = []
    host = 'wglj.suzhou.gov.cn'
    listing = '<a href="https://evil.test/event">活动</a>' + ''.join(
        f'<a href="/szwhgdhlyj/hdxx/202610/{str(i)*32}.shtml">测试活动</a>' for i in range(1, 5))

    def transport(request):
        visited.append(str(request.url))
        if request.url.path == '/robots.txt':
            return httpx.Response(404)
        return httpx.Response(200, text=listing if request.url.path.endswith('list.shtml') else ARTICLE,
                              headers={'Content-Type': 'text/html'})

    client = PublicClient(transport=httpx.MockTransport(transport), interval=0)
    try:
        source = CultureTourismSource(client=client, max_items=2)
        report = run_pipeline(tmp_path / 'bounded.sqlite3', [source], request_client=client)
        assert report['pagesCollected'] == 3 and report['eventsProcessed'] == 2
        assert all(host in url for url in visited)
    finally:
        client.close()


def test_empty_olympic_feed_is_failed_and_context_is_retained(tmp_path):
    def transport(request):
        if request.url.path == '/robots.txt':
            return httpx.Response(404)
        if request.url.path.endswith('gethd.html'):
            return httpx.Response(200, json={'lists': []})
        return httpx.Response(200, text='<script>$.get("/Activity/gethd.html")</script>',
                              headers={'Content-Type': 'text/html'})

    client = PublicClient(transport=httpx.MockTransport(transport), interval=0)
    try:
        report = run_pipeline(tmp_path / 'empty.sqlite3', [OlympicSource(client=client)], request_client=client)
        assert report['status'] == 'Failed' and report['eventsStored'] == 0
        assert report['rawRecordsCollected'] == 2
        assert 'no event records' in report['attempts'][0]['error']
    finally:
        client.close()


def test_rejected_details_are_durable_and_coverage_is_job_scoped(tmp_path):
    path = copy_registry(tmp_path)

    class Source(CultureTourismSource):
        def collect(self):
            return [record(ARTICLE)]

    db = tmp_path / 'coverage.sqlite3'
    report = run_pipeline(db, [Source()])
    attach_coverage(db, report, registry_path=path)
    assert report['sourceCoverage']['evidenceGenerated'] == 10

    class Changed(Source):
        def collect(self):
            return [record(ARTICLE.replace('10月11日，', '近日，'))]

    old = snapshot(db)['events']
    failed = run_pipeline(db, [Changed()])
    attach_coverage(db, failed, registry_path=path)
    coverage = failed['sourceCoverage']
    assert coverage['failedSources'] == [Source.source_id]
    assert coverage['eventsExtracted'] == coverage['evidenceGenerated'] == 0
    assert coverage['currentEventEvidenceRecords'] == 10
    assert snapshot(db)['events'] == old
    row = next(d for d in load_registry(path) if d.source_id == Source.source_id)
    assert row.crawl_status == 'FAILED' and 'leading event date' in row.reason
    with connect(db) as con:
        assert con.execute('SELECT COUNT(*) FROM crawler_raw_items').fetchone()[0] == 2
        assert not con.execute('PRAGMA foreign_key_check').fetchall()


def test_tier1_cli_records_failures_and_never_visits_wechat(monkeypatch, tmp_path, capsys):
    import crawler.run as cli
    visited = []
    path = copy_registry(tmp_path)

    def transport(request):
        visited.append(str(request.url))
        if request.url.path == '/robots.txt':
            return httpx.Response(200, text='User-agent: *\nDisallow: /')
        raise AssertionError('Robots denied all bodies; no protected page request allowed')

    client = PublicClient(transport=httpx.MockTransport(transport), interval=0)
    monkeypatch.setattr(cli, 'PublicClient', lambda **kwargs: client)
    output = tmp_path / 'report.json'
    monkeypatch.setattr(sys, 'argv', ['crawler.run', '--tier1', '--registry', str(path),
                                     '--db', str(tmp_path / 'all.sqlite3'), '--coverage-report', str(output)])
    assert cli.main() == 2
    report = json.loads(capsys.readouterr().out)
    coverage = report['sourceCoverage']
    assert coverage['registeredSources'] == len(load_registry(path))
    assert coverage['attemptedSources'] == 10
    assert len(coverage['failedSources']) == 10
    assert coverage['eventsExtracted'] == coverage['evidenceGenerated'] == 0
    assert output.exists() and client.client.is_closed
    assert all('wechat' not in url and 'weixin' not in url for url in visited)
    assert all(d.reason for d in load_registry(path) if d.crawl_status == 'FAILED')
    assert next(d for d in load_registry(path) if d.platform == 'WeChat').crawl_status == 'MANUAL_VERIFICATION_REQUIRED'


@pytest.mark.parametrize("crawl_url", ["https://other.test/", "https://www.sipac.gov.cn:444/", "http://www.sipac.gov.cn/"])
def test_registry_crawl_endpoint_cannot_leave_the_registered_https_host(tmp_path, crawl_url):
    path = copy_registry(tmp_path)
    data = yaml.safe_load(path.read_text(encoding='utf-8'))
    data['sources'][0]['crawl_url'] = crawl_url
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError):
        load_registry(path)


def test_tournament_brand_year_is_not_an_event_year():
    raw = ARTICLE.replace('2026苏州测试文化节', '新建元2034杯足球赛')
    with pytest.raises(ValueError, match='year is not explicit'):
        extract(record(raw), 'government')
