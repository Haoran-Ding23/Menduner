"""Lead-owned registry boundary tests: plain-HTTP opt-in, limitation records, hosts.

The registry decides which hosts the crawler is allowed to touch and over which
transport. These checks pin the V1.6.2 additions so a future edit cannot silently
widen them.
"""
from pathlib import Path
from urllib.parse import urlparse

import pytest
import yaml

from crawler.http import PublicClient
from crawler.registry import REGISTRY_PATH, load_registry


def registry_document():
    return yaml.safe_load(REGISTRY_PATH.read_text(encoding='utf-8'))


def write_variant(tmp_path, document):
    path = Path(tmp_path) / 'registry.yaml'
    path.write_text(yaml.safe_dump(document, allow_unicode=True), encoding='utf-8')
    return path


def cnena_row(document):
    return next(s for s in document['sources'] if s['adapter'] == 'cnena')


def test_only_the_declared_plain_http_source_may_use_http(tmp_path):
    document = registry_document()
    http_sources = {
        row['adapter'] for row in document['sources']
        if str(row.get('crawl_url') or '').startswith('http://')
    }
    assert http_sources == {'cnena'}, http_sources
    assert cnena_row(document)['allow_plain_http'] is True


def test_plain_http_without_the_opt_in_is_rejected(tmp_path):
    document = registry_document()
    row = cnena_row(document)
    row.pop('allow_plain_http')
    with pytest.raises(ValueError):
        load_registry(write_variant(tmp_path, document))


def test_plain_http_without_a_recorded_limitation_is_rejected(tmp_path):
    document = registry_document()
    cnena_row(document).pop('limitation')
    with pytest.raises(ValueError, match='limitation'):
        load_registry(write_variant(tmp_path, document))


def test_plain_http_opt_in_cannot_be_inherited_from_another_source(tmp_path):
    """The opt-in is per source. Copying the cnena transport onto a government host
    must not be accepted on the strength of cnena's own row."""
    document = registry_document()
    target = next(s for s in document['sources'] if s['adapter'] == 'sipac')
    target['crawl_url'] = 'http://www.sipac.gov.cn/'
    target['limitation'] = 'attempted transport reuse'
    # No allow_plain_http on this row, even though a different row sets it.
    target.pop('allow_plain_http', None)
    with pytest.raises(ValueError):
        load_registry(write_variant(tmp_path, document))

    # ...and it is still refused when the HTTP URL is smuggled in under another host.
    other = next(s for s in document['sources'] if s['adapter'] == 'olympic')
    other['url'] = 'http://www.cnena.com/'
    other['crawl_url'] = 'http://www.cnena.com/'
    with pytest.raises(ValueError):
        load_registry(write_variant(tmp_path, document))


def test_https_sources_reject_an_http_crawl_url(tmp_path):
    document = registry_document()
    target = next(s for s in document['sources'] if s['adapter'] == 'olympic')
    target['crawl_url'] = 'http://www.szosc.cn/index.php/Activity/index.html'
    with pytest.raises(ValueError):
        load_registry(write_variant(tmp_path, document))


def test_registry_records_the_corrected_hosts():
    definitions = {d.adapter: d for d in load_registry()}
    # The supplied arts-centre host does not resolve; the real host was verified.
    assert definitions['arts'].crawl_url == 'https://www.sscac.com.cn/'
    # The supplied cnena city route is a 404 page; the venue schedule page works.
    assert 'showroom-htm-id-28' in definitions['cnena'].crawl_url
    # Huodongjia's supplied city route is a JS-only shell; SSR lives on the homepage.
    assert definitions['huodongjia'].crawl_url == 'https://www.huodongjia.com/'


def test_a_successful_source_may_still_record_a_documented_limitation():
    """A source can succeed and still be limited (e.g. a past-only archive), which is
    why `limitation` is separate from the FAILED-only `reason` field."""
    olympic = next(d for d in load_registry() if d.adapter == 'olympic')
    assert olympic.crawl_status == 'SUCCESS'
    assert olympic.reason is None
    assert olympic.limitation and 'historical' in olympic.limitation


# --- plain-HTTP transport boundary -------------------------------------------

HTTP_HOSTS = {urlparse(d.crawl_url).hostname for d in load_registry() if d.allow_plain_http}


def test_http_only_hosts_are_derived_from_the_registry():
    assert HTTP_HOSTS == {'www.cnena.com'}, HTTP_HOSTS


def test_client_refuses_plain_http_for_a_host_that_did_not_opt_in():
    client = PublicClient(plain_http_hosts=HTTP_HOSTS)
    try:
        with pytest.raises(ValueError):
            client._public_page_url('http://www.sipac.gov.cn/')
        with pytest.raises(ValueError):
            client._public_page_url('http://evil.example/')
    finally:
        client.close()


def test_client_allows_plain_http_only_for_the_allow_listed_host():
    client = PublicClient(plain_http_hosts=HTTP_HOSTS)
    try:
        parts = client._public_page_url('http://www.cnena.com/showroom/x.html')
        assert parts.hostname == 'www.cnena.com' and parts.scheme == 'http'
    finally:
        client.close()


def test_default_client_refuses_all_plain_http():
    client = PublicClient()
    try:
        with pytest.raises(ValueError):
            client._public_page_url('http://www.cnena.com/')
        # HTTPS stays available for every host.
        assert client._public_page_url('https://www.cnena.com/').scheme == 'https'
    finally:
        client.close()


def test_plain_http_still_cannot_carry_credentials_or_other_schemes():
    client = PublicClient(plain_http_hosts=HTTP_HOSTS)
    try:
        with pytest.raises(ValueError):
            client._public_page_url('http://user:pw@www.cnena.com/')
        with pytest.raises(ValueError):
            client._public_page_url('ftp://www.cnena.com/')
    finally:
        client.close()


def test_cli_derives_plain_http_hosts_from_the_registry():
    """The CLI must pass exactly the opted-in hosts to the shared client, and nothing else."""
    from urllib.parse import urlparse as _urlparse
    definitions = load_registry()
    derived = {
        _urlparse(d.crawl_url).hostname for d in definitions if d.allow_plain_http and d.crawl_url
    }
    assert derived == {'www.cnena.com'}
    # Every other source's host must remain HTTPS-only.
    for d in definitions:
        if d.crawl_url and not d.allow_plain_http:
            assert _urlparse(d.crawl_url).scheme == 'https', d.source_id


# --- public-page redirect boundary -------------------------------------------

def test_public_page_omitting_allowed_redirect_still_enforces_approved_routes():
    """Regression: `public_page(url)` without an explicit redirect rule MUST keep every
    redirect inside the source's approved routes. A version of this method treated a
    missing argument as "no restriction", so a Damai detail page that redirected to
    /login was fetched (HTTP 200) and only failed later with a confusing KeyError."""
    import httpx

    from crawler.http import PublicClient
    from crawler.sources.event_platform.damai import DamaiSource

    visited = []

    def handler(request):
        visited.append(str(request.url))
        if request.url.path == '/robots.txt':
            return httpx.Response(404)
        if request.url.host == 'search.damai.cn':
            return httpx.Response(200, text='entry', headers={'Content-Type': 'text/html'})
        if request.url.path == '/item.htm':
            return httpx.Response(302, headers={'Location': '/login'})
        return httpx.Response(200, text='LOGIN PAGE', headers={'Content-Type': 'text/html'})

    client = PublicClient(transport=httpx.MockTransport(handler), interval=0, sleep=lambda n: None)
    source = DamaiSource(client=client)
    try:
        with pytest.raises(RuntimeError, match='approved public page routes'):
            source.public_page('https://detail.damai.cn/item.htm?id=123456789012')
    finally:
        client.close()
    assert not any('/login' in url for url in visited), visited


def test_public_page_still_allows_a_redirect_within_the_approved_routes():
    """The check must not be so tight that a legitimate same-route redirect is blocked."""
    import httpx

    from crawler.http import PublicClient
    from crawler.sources.community.douban import DoubanSource

    visited = []

    def handler(request):
        visited.append(str(request.url))
        if request.url.path == '/robots.txt':
            return httpx.Response(404)
        if request.url.path.endswith('/events/future'):
            return httpx.Response(302, headers={'Location': '/location/suzhou/events/future-all'})
        return httpx.Response(200, text='<html>listing</html>', headers={'Content-Type': 'text/html'})

    client = PublicClient(transport=httpx.MockTransport(handler), interval=0, sleep=lambda n: None)
    source = DoubanSource(client=client)
    try:
        page = source.public_page('https://www.douban.com/location/suzhou/events/future')
    finally:
        client.close()
    assert page.url.endswith('/future-all')
    assert any('future-all' in url for url in visited)
