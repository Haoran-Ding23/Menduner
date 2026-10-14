"""CNENA (中国会展网 / China Exhibition Network) 苏州国际博览中心 exhibition adapter.

Why this source is registered: the venue's own site (www.suzhouexpo.com) publishes no usable
schedule, and CNENA's venue page is the one public, server-rendered place that carries the
苏州国际博览中心 展会排期 with explicit ``开幕`` dates - exhibition demand is one of the
strongest hotel-demand signals for the Suzhou market.

Ground truth re-verified live on 2026-10-13 through the approved route:
  * ``http://www.cnena.com/robots.txt`` -> 200, text/plain, 0 bytes: no directives at all.
  * ``http://www.cnena.com/showroom/showroom-htm-id-28.html`` -> 200, charset=gb2312, 92,182
    bytes, 150 schedule rows each carrying an explicit ``开幕：YYYY-MM-DD`` cell and one
    ``bencandy-htm-fid-*-id-*.html`` detail link (150 distinct links).
  * ``http://www.cnena.com/showroom/bencandy-htm-fid-1-id-48684.html`` -> 200, gb2312, with
    explicit ``开幕日期`` / ``结束日期`` / ``展会地点`` / ``组织机构`` labels.
  * The route originally supplied in the registry, ``http://www.cnena.com/Show/city/suzhou/``,
    answers HTTP 200 but is the site's 404 page; it is recorded here and never requested.

TRANSPORT LIMITATION (accepted, explicit, permanent): this host is reachable over plain HTTP
only. ``https://www.cnena.com/`` fails with ``CERTIFICATE_VERIFY_FAILED: Hostname mismatch``
because its certificate is not valid for www.cnena.com, and TLS verification is never disabled
for any host. Response integrity is therefore NOT cryptographically verifiable: every published
value is an observation of an unauthenticated response, so all claims stay ``Unverified`` /
``Needs Review`` and can never be ``Verified``. The limitation is recorded in the registry row
(``allow_plain_http: true`` plus its ``limitation`` text) and in every run's ``investigation``.

Routes and robots: only path-based routes are requested. The site publishes no robots rules
(0-byte 200), but its own ``Disallow: /*?*`` convention is honoured anyway, so no query-string
URL is ever built, resolved or followed, and a redirect must stay on www.cnena.com AND keep the
http scheme. Publication/member timestamps are never event dates; only an explicit ``开幕``
label qualifies, and a schedule row without one is rejected with a recorded reason.

``city`` is deliberately left null: the only city evidence on this route is the venue string
(苏州国际博览中心), and the source's own title/venue values are never rewritten or extended.
"""

import re
from datetime import date
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from crawler.extractor import base, set_field, text
from crawler.sources.event_platform.public_access import PublicAccessSource, blocked_page

HOST = 'www.cnena.com'
BASE_URL = 'http://' + HOST + '/'
# The verified live route: 苏州国际博览中心 展会排期 (venue id 28), path-based, no query string.
VENUE_URL = BASE_URL + 'showroom/showroom-htm-id-28.html'
VENUE_PATH = '/showroom/showroom-htm-id-28.html'
VENUE_NAME = '苏州国际博览中心'
# The registry's originally supplied city route answers 200 but is the site's 404 page.
SUPPLIED_CITY_ROUTE = BASE_URL + 'Show/city/suzhou/'
DETAIL_PATH = re.compile(r'^/showroom/bencandy-htm-fid-(\d{1,6})-id-(\d{1,9})\.html$')
PLAIN_HTTP_LIMITATION = (
    'www.cnena.com is reachable over plain HTTP only (its TLS certificate is not valid for the '
    'hostname); response integrity is not cryptographically verifiable, so every claim from this '
    'source stays Unverified/Needs Review and can never be Verified'
)

# The venue page cell that carries the fair's opening day, e.g. ``开幕：2026-12-04``.
OPENING_CELL = re.compile(r'^开幕\s*(?:日期)?\s*[：:]\s*(\d{4}-\d{2}-\d{2})$')
# Detail-page labels, e.g. ``开幕日期：2026-12-04`` / ``结束日期：`` / ``展会地点：`` / ``主办单位：``.
OPENING_LINE = re.compile(r'^开幕\s*(?:日期)?\s*[：:]\s*(.*)$')
ENDING_LINE = re.compile(r'^结束\s*(?:日期)?\s*[：:]\s*(.*)$')
VENUE_LINE = re.compile(r'^展会地点\s*[：:]\s*(.*)$')
ORGANIZER_LINE = re.compile(r'^主办单位\s*[：:]\s*(.*)$')
# A value that continues on the next line stops at the next known label.
FOLLOWING_LABEL = re.compile(
    r'^(?:开幕|结束|展会地点|主办单位|联合主办|承办单位|协办单位|支持单位|组织机构|展会发布平台'
    r'|参展联络|组委会联络处)\s*[：:]'
)
# An inline value is cut at the next label; the row's ``会员：`` publisher account is not a name.
NEXT_LABEL = re.compile(r'\s*(?:联合主办|承办单位|协办单位|支持单位|主办单位|展会地点|开幕|结束)\s*[：:]')
# The live venue page labels its own identity ``展馆名称：<a>苏州国际博览中心</a>``.
VENUE_PAGE_NAME = re.compile(r'(?:展馆|场馆)名称\s*[：:]\s*([^\s：:]{2,40})')
COMPLETE_DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')

# Explicit keyword evidence from the record's own published title only; anything else is 'others'.
CULTURE_TITLE = re.compile(r'文创|文化|艺术|书画|非遗|博物馆|美术|摄影|动漫|图书|佛事|佛文化')
BUSINESS_TITLE = re.compile(
    r'展览会|博览会|交易会|展销会|展会|产业展|工博会|大会|论坛|峰会|年会|采购会|订货会'
)
# A published title that ends in 展 (never 发展) explicitly names the record an exhibition, which
# is the source vocabulary this venue schedule is built from.
BUSINESS_TITLE_SUFFIX = re.compile(r'(?<!发)展$')


def iso_date(value):
    """``YYYY-MM-DD`` for a complete calendar date, else None (no partial or invented dates)."""
    if not isinstance(value, str) or not COMPLETE_DATE.fullmatch(value.strip()):
        return None
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except ValueError:
        return None


def cell_text(node):
    return text(node.get_text(' ', strip=True))


def detail_url(href):
    """Absolute plain-HTTP URL for one approved detail href, else None.

    Off-host, off-route, query-string and non-http links resolve to None and are therefore
    never requested; the discovery page carries absolute query-string links of its own.
    """
    if not isinstance(href, str) or not href.strip():
        return None
    resolved = urljoin(VENUE_URL, href.strip())
    if not CnenaSource.is_public_url(resolved):
        return None
    return resolved


def schedule_rows(content):
    """Explicit 开幕 rows from the venue schedule page, in page order.

    A schedule row is a ``<tr>`` with exactly three direct cells (title link, ``会员：`` and the
    ``开幕：YYYY-MM-DD`` cell) and exactly one approved detail link. Rows that look like schedule
    rows but carry no complete explicit 开幕 date are returned as rejections with a reason, so no
    row is ever dropped silently. Returns ``(rows, rejected)``.
    """
    soup = BeautifulSoup(content, 'html.parser')
    rows = []
    rejected = []
    for node in soup.find_all('tr'):
        cells = node.find_all('td', recursive=False)
        if len(cells) != 3:
            continue
        links = [url for url in (detail_url(a['href']) for a in node.select('a[href]')) if url]
        if len(links) != 1 or not cell_text(cells[0]):
            continue
        title = cell_text(cells[0].find('a', href=True) or cells[0])
        opening_cell = cell_text(cells[2]) or ''
        opening = OPENING_CELL.fullmatch(opening_cell)
        if not opening:
            rejected.append({
                'title': title,
                'url': links[0],
                'reason': 'schedule row carries no explicit 开幕：YYYY-MM-DD label (cell=' +
                          (opening_cell[:60] or '(empty)') + '); no detail page published for it',
            })
            continue
        start = iso_date(opening[1])
        if not start:
            rejected.append({
                'title': title,
                'url': links[0],
                'reason': 'schedule row 开幕 value is not a real calendar date (cell=' +
                          opening_cell[:60] + ')',
            })
            continue
        rows.append({
            'title': title,
            'member': cell_text(cells[1]),
            'opening': start,
            'url': links[0],
            'id': DETAIL_PATH.fullmatch(urlparse(links[0]).path)[2],
        })
    return rows, rejected


def venue_page_identity(content):
    """The venue this page identifies itself as, or None when the page shape changed."""
    soup = BeautifulSoup(content, 'html.parser')
    title = cell_text(soup.title) if soup.title else None
    if not title or VENUE_NAME not in title:
        return None
    named = VENUE_PAGE_NAME.search(text(soup.get_text(' ', strip=True)) or '')
    if not named or named[1] != VENUE_NAME:
        return None
    return named[1]


def detail_lines(soup):
    """Visible text lines of a detail page, one per ``<br>``/block, scripts removed."""
    for node in soup.select('script,style'):
        node.decompose()
    return [line for line in (text(item) for item in soup.get_text('\n', strip=True).splitlines())
            if line]


def labelled_value(lines, pattern):
    """Value of the first explicit ``label：value`` line, plus its evidence snippet.

    A label-only line (the live markup puts the value behind a ``<br>``) reads the next
    non-label line, and an inline value is cut at the next label. No value is ever guessed.
    """
    for index, line in enumerate(lines):
        matched = pattern.match(line)
        if not matched:
            continue
        inline = text(matched[1])
        if inline:
            return NEXT_LABEL.split(inline)[0].strip() or None, line
        for following in lines[index + 1:index + 4]:
            if FOLLOWING_LABEL.match(following):
                break
            value = text(following)
            if value:
                return NEXT_LABEL.split(value)[0].strip() or None, line + ' ' + value
        return None, line
    return None, None


def title_category(name):
    """Category only on explicit title evidence; otherwise the schema default 'others'."""
    for category, pattern, evidence in (
        ('culture', CULTURE_TITLE, 'title contains an explicit cultural-event keyword'),
        ('business', BUSINESS_TITLE, 'title contains an explicit exhibition/trade-fair keyword'),
        ('business', BUSINESS_TITLE_SUFFIX, 'title explicitly ends in 展 (exhibition)'),
    ):
        matched = pattern.search(name)
        if matched:
            return category, evidence + '=' + matched[0]
    return 'others', 'no explicit business/culture keyword in the published title (default)'


def cnena_exhibition(item):
    """Deterministic extraction for one CNENA exhibition detail page.

    Only explicit labelled fields are read: ``开幕``/``结束`` dates, ``展会地点`` and
    ``主办单位``. Publication and member timestamps are never substituted for an event date.
    """
    if blocked_page(item.raw_content):
        raise ValueError('Login/CAPTCHA/access wall: raw retained, no event published')
    if (not CnenaSource.is_public_url(item.original_url)
            or not DETAIL_PATH.fullmatch(urlparse(item.original_url).path)):
        raise ValueError('CNENA event data must come from an approved public detail page')
    soup = BeautifulSoup(item.raw_content, 'html.parser')
    heading = soup.find('h1') or soup.find('h2')
    name = cell_text(heading) if heading else None
    if not name:
        raise ValueError('CNENA detail page has no explicit exhibition heading (h1/h2); '
                         'no name is invented')
    lines = detail_lines(soup)

    start, start_snippet = labelled_value(lines, OPENING_LINE)
    start = iso_date(start)
    if not start:
        raise ValueError(
            'No explicit 开幕/开幕日期 YYYY-MM-DD label on this detail page; publication and '
            'member timestamps are never used as event dates'
        )
    finish, finish_snippet = labelled_value(lines, ENDING_LINE)
    if finish:
        parsed_finish = iso_date(finish)
        if not parsed_finish:
            raise ValueError('CNENA 结束/结束日期 value is not a complete YYYY-MM-DD date')
        if parsed_finish < start:
            raise ValueError('CNENA 结束 date precedes the 开幕 date; interval rejected')
        finish = parsed_finish
    venue, venue_snippet = labelled_value(lines, VENUE_LINE)
    if not venue:
        raise ValueError('No explicit 展会地点 label on this detail page; the venue is never '
                         'inferred from the title or the schedule page')
    organizer, organizer_snippet = labelled_value(lines, ORGANIZER_LINE)
    if (item.locator and COMPLETE_DATE.fullmatch(str(item.locator))
            and str(item.locator) != start):
        raise ValueError('Detail page 开幕 date ' + start +
                         ' does not match the discovered schedule row date ' + str(item.locator))

    event = base(item)
    set_field(event, 'event_name', name, snippet='h1/h2=' + name, confidence=0.9,
              method='explicit_detail_page_exhibition_heading')
    set_field(event, 'start_date', start, snippet='开幕/开幕日期 label: ' + str(start_snippet),
              confidence=0.9,
              method='explicit_labelled_opening_date (publication timestamps never substituted)')
    if finish:
        set_field(event, 'end_date', finish, snippet='结束/结束日期 label: ' + str(finish_snippet),
                  confidence=0.9, method='explicit_labelled_closing_date')
    set_field(event, 'venue', venue, snippet='展会地点 label: ' + str(venue_snippet),
              confidence=0.85, method='explicit_labelled_exhibition_venue_field')
    # The labelled venue is the only location claim made here; no street address is invented.
    set_field(event, 'location', venue, snippet='展会地点 label: ' + str(venue_snippet),
              confidence=0.7,
              method='explicit_labelled_exhibition_venue_field (not street-address enrichment)')
    if organizer:
        set_field(event, 'organizer', organizer,
                  snippet='主办单位 label: ' + str(organizer_snippet), confidence=0.8,
                  status='Needs Review', method='explicit_labelled_organizer_field')
    category, why = title_category(name)
    set_field(event, 'category', category, snippet=why + ' | event_name=' + name,
              confidence=0.6, status='Needs Review', method='event_title_published_keyword_rule')
    return event


def plain_http_refusal(client):
    """The explicit reason a client will not fetch this source's plain-HTTP origin, else None."""
    probe = getattr(client, '_public_page_url', None) or getattr(client, '_public_url', None)
    if probe is None:
        return None
    try:
        probe(VENUE_URL)
    except Exception as exc:  # noqa: BLE001 - the reason is recorded verbatim, no request made
        return str(exc)
    return None


class CnenaSource(PublicAccessSource):
    source_id = 'platform-cnena-suzhou'
    source_name = 'China Exhibition Network'
    kind = 'event_platform'
    source_url = BASE_URL
    crawl_url = VENUE_URL
    extractor = 'cnena_exhibition'
    # Registry-mirrored opt-in: this host is plain HTTP only (invalid certificate for its own
    # hostname). TLS verification is never disabled for any host.
    allow_plain_http = True
    supplied_city_route = SUPPLIED_CITY_ROUTE

    @staticmethod
    def is_public_url(url):
        """Approved routes only: plain-HTTP, same host, no query, no credentials, no fragment."""
        parts = urlparse(url)
        return (
            parts.scheme == 'http'
            and parts.hostname == HOST
            and parts.port in (None, 80)
            and parts.username is None
            and parts.password is None
            and not parts.query
            and not parts.fragment
            and (parts.path == VENUE_PATH or DETAIL_PATH.fullmatch(parts.path) is not None)
        )

    def collect(self):
        items = []
        self.investigation = {
            'scope': 'verified 苏州国际博览中心 schedule page + bounded detail pages',
            'routes': 'path-based only; no query-string URL is ever built or requested',
            'transport': 'plain HTTP only: ' + PLAIN_HTTP_LIMITATION,
            'supplied_city_route': SUPPLIED_CITY_ROUTE,
            'supplied_city_route_requests': 0,
            'schedule_rows_seen': 0,
            'schedule_rows_rejected': 0,
            'rejected_rows': [],
            'detail_pages_fetched': 0,
        }
        refusal = plain_http_refusal(self.client)
        if refusal:
            self.errors.append({
                'url': VENUE_URL,
                'error': 'Plain-HTTP collection refused by the configured client (' + refusal +
                         '); this host cannot be collected over HTTPS (its certificate is not '
                         'valid for the hostname) and TLS verification is never disabled, so no '
                         'request was made. Wire the registry allow_plain_http flag through '
                         'crawler.run -> PublicClient(plain_http_hosts=...)',
            })
            return [*self.policy_items, *items]
        if str(self.crawl_url) != VENUE_URL:
            # The registry may still point at the supplied 404 city route; it is never requested.
            self.warnings.append(
                'Configured crawl URL ' + str(self.crawl_url) + ' is not the verified ' +
                VENUE_NAME + ' schedule page; ' + VENUE_URL +
                ' was used instead and the configured route was not requested')
        try:
            venue_page = self.public_page(VENUE_URL)
        except Exception as exc:
            # Robots/access policy is a stop condition for the whole host.
            self.errors.append({'url': VENUE_URL, 'error': str(exc)})
            return [*self.policy_items, *items]
        items.append(self.item(venue_page, key='cnena-venue-28', is_event=False,
                              extractor='context'))
        if blocked_page(venue_page.content):
            self.errors.append({'url': venue_page.url,
                                'error': 'Access wall; no login/CAPTCHA/private route attempt'})
            return [*self.policy_items, *items]
        identity = venue_page_identity(venue_page.content)
        if identity is None:
            self.errors.append({
                'url': venue_page.url,
                'error': 'Fetched page no longer identifies itself as the ' + VENUE_NAME +
                         ' schedule (title/场馆名称 check failed); no event is published from an '
                         'unverified page state',
            })
            return [*self.policy_items, *items]
        rows, rejected = schedule_rows(venue_page.content)
        self.investigation['schedule_rows_seen'] = len(rows) + len(rejected)
        self.investigation['schedule_rows_rejected'] = len(rejected)
        self.investigation['rejected_rows'] = rejected[:20]
        if not rows:
            self.errors.append({
                'url': venue_page.url,
                'error': 'No schedule row carries an explicit 开幕：YYYY-MM-DD label; the page '
                         'shape changed and no event is invented',
            })
            return [*self.policy_items, *items]

        for row in rows[:self.max_items]:
            if not self.is_public_url(row['url']):
                self.errors.append({'url': row['url'],
                                    'error': 'Detail link is not an approved path-based '
                                             'same-host route; no request made'})
                continue
            try:
                detail = self.public_page(row['url'])
            except PermissionError as exc:
                self.errors.append({'url': row['url'], 'error': str(exc)})
                break  # Robots/access policy: stop this host.
            except RuntimeError as exc:
                self.errors.append({'url': row['url'], 'error': str(exc)})
                break  # Redirect/transport boundary: stop this host.
            except Exception as exc:
                # One unavailable detail page must not hide the other dated rows.
                self.errors.append({'url': row['url'], 'error': str(exc)})
                continue
            items.append(self.item(detail, key='cnena-fair-' + row['id'],
                                   extractor=self.extractor, locator=row['opening']))
            self.investigation['detail_pages_fetched'] += 1
            if blocked_page(detail.content):
                self.errors.append({'url': detail.url,
                                    'error': 'Detail access wall; no login/CAPTCHA/private '
                                             'route attempt'})
                break
        return [*self.policy_items, *items]
