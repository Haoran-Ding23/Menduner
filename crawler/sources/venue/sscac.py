"""苏州文化艺术中心 (SSCAC) performance calendar — the host's own public JSON API.

Why this source changed on 2026-10-15
-------------------------------------
The V1.6 reconnaissance recorded this host as unusable: ``www.sscac.com.cn`` serves a
~380 KB Nuxt shell whose whole visible text is a few hundred characters and whose
``window.__NUXT__`` payload is ``state:{list:{list:[]}}``. The V1.6.2 verdict was
``NEEDS_DEEPER_WORK`` and the registry row was audit-only ("client-rendered Nuxt shell with
an empty state payload").

The shell is real, but it is not empty — it is a client-rendered application, and the
shell's own published JavaScript carries the calendar's API. Read live that way (TLS
verification on, no credential of any kind, robots permissive: ``/robots.txt`` is a 0-byte
200):

  * ``https://www.sscac.com.cn/`` -> 200 text/html, the Nuxt shell. Its ``<script src>``
    list is the only thing that changes between deployments.
  * the shell's own bundle ``/_nuxt/<hash>.js`` contains the API base
    ``https://www.sscac.com.cn/sue/api`` and the endpoint literals
    ``/cinema/findYanYiList`` and ``/cinema/showDramaInfoList``.
  * ``POST /sue/api/cinema/findYanYiList`` with the site's own filter body
    ``{"currentPage": 1, "pageSize": 100, "status": "1", "orders":[...]}`` -> 200 JSON,
    ``code:0``, 31 upcoming performances (2026-10-16 .. 2027-07-10) carrying
    ``projectName`` / ``projectStartTime`` / ``projectEndTime`` / ``projectTypeId`` /
    ``siteName``.
  * ``POST /sue/api/cinema/showDramaInfoList`` with the site's own ``startTime`` filter
    (``moment(new Date).format('YYYY-MM-DD')``, which its own page sends) -> the same
    upcoming programme. Without that filter the endpoint answers its full 2,909-record
    archive reaching back to 1992, which is why the filter is part of the request and a
    finished record is never republished as live demand.

So this is not a protected API: it is the public JSON the venue's front-end calls for every
visitor, reached exactly as the browser reaches it. Three things are deliberately part of
the contract rather than conveniences:

  * the endpoint route is never assumed. Every run reads the host's own published bundle and
    fails closed with a recorded reason when it stops advertising ``/sue/api``;
  * only pages 1..``MAX_PAGES`` of ``PAGE_SIZE`` rows are requested, and a record is skipped
    with a recorded reason when it is deleted, carries no complete start date, or already
    finished;
  * both public lists describe the same programme, so the source's own record id is the
    identity: a record is published once even though two endpoints carry it.

Item contract: an event item's raw content is that record's own JSON object exactly as the
API served it, and the enclosing response is retained once as a context item. Field claims
therefore come only from explicit source fields — the published hall (``siteName``) becomes
the location, the venue is the site's own identity (checked in ``collect``), and the category
comes from the published ``projectTypeId`` through an explicit keyword rule.
"""

import json
import re
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urljoin, urlparse

from crawler.extractor import base, full_date, set_field, text
from crawler.sources.event_platform.public_access import PublicAccessSource

HOST = 'www.sscac.com.cn'
BASE_URL = 'https://' + HOST
# The registry's crawl URL is the site root; this page is the venue's own 演艺 listing.
ENTRY_PATH = '/'
LISTING_PATH = '/theatre-active'
API_ROOT = '/sue/api'
YANYI_PATH = API_ROOT + '/cinema/findYanYiList'
DRAMA_PATH = API_ROOT + '/cinema/showDramaInfoList'
ENDPOINTS = (YANYI_PATH, DRAMA_PATH)
# Deploy-time asset names are content-hashed; only the path shape is stable.
BUNDLE_PATH = re.compile(r'^/_nuxt/[A-Za-z0-9_\-]{6,64}\.js$')
SCRIPT_SRC = re.compile(r'<script[^>]+src=["\']([^"\']+)["\']', re.I)
# A published JS asset is served as application/javascript (sometimes text/plain); it is
# requested only to read the API route the host itself advertises, never executed.
JS_MEDIA = ('javascript', 'text/plain')
# Bounded server page: the live listing answers its 31 upcoming rows in a single page.
PAGE_SIZE = 100
MAX_PAGES = 2
# The venue's own identity: the host is the venue's official site and the served page title
# must still say so (checked in collect()). The performance's own hall is kept as location.
VENUE_NAME = '苏州文化艺术中心'
TITLE_MARKER = '苏州文化艺术中心'
LOCAL_TIMEZONE = timezone(timedelta(hours=8))
# The performance types this venue publishes on its own calendar. Anything else stays the
# schema default 'others' rather than being guessed into 'culture'.
PERFORMANCE_TYPE = re.compile(
    r'音乐剧|话剧|舞蹈|舞剧|音乐|歌剧|戏曲|儿童剧|高清放映|演唱会|魔术|杂技|曲艺|舞台剧|沉浸式'
)


def local_today():
    """The calendar's own local day (Asia/Shanghai), used only to skip finished shows."""
    return datetime.now(LOCAL_TIMEZONE).date()


def is_envelope_ok(document):
    """True only for this API's own success envelope (``code:0`` with a record list)."""
    if not isinstance(document, dict) or document.get('code') != 0:
        return False
    obj = document.get('obj')
    return isinstance(obj, dict) and isinstance(obj.get('records'), list)


def record_date(value):
    """``YYYY-MM-DD`` of an explicit start/end value, else None (never a partial date)."""
    return full_date(value) if isinstance(value, str) else None


def record_is_usable(record):
    """``(keep, reason)`` for one API record, judged only on explicit fields.

    A record is dropped only for a stated reason: it is marked deleted, it has no id, it has
    no name, or it has no complete start date. A finished show is dropped by the caller
    against the run day, so this function stays independent of the clock.
    """
    if not isinstance(record, dict):
        return False, 'record is not a JSON object'
    if record.get('deleted'):
        return False, 'record is marked deleted by the source'
    if not text(record.get('projectName')):
        return False, 'record carries no projectName'
    if record_date(record.get('projectStartTime')) is None:
        return False, ('record carries no complete YYYY-MM-DD projectStartTime (value=' +
                       str(record.get('projectStartTime'))[:40] + ')')
    return True, None


def request_body(endpoint, page_number, today):
    """The request body this venue's own front-end sends, bounded to one page.

    ``findYanYiList`` is the venue's performance calendar and needs no date filter (its live
    answer is already the upcoming programme). ``showDramaInfoList`` answers its whole
    archive back to 1992 without the ``startTime`` filter its own 戏剧 page passes, so the
    filter is carried explicitly instead of paging 30 archive pages to find live rows.
    """
    body = {
        'currentPage': page_number,
        'pageSize': PAGE_SIZE,
        'status': '1',
        'orders': [{'column': 'projectStartTime', 'sort': 'asc'}],
    }
    if endpoint == DRAMA_PATH:
        body['startTime'] = today.isoformat()
    return body


def published_endpoint_bundle(bundles):
    """The first published bundle that advertises this API, else None.

    The endpoint is taken from the host's own JavaScript rather than from this module: the
    caller fetches the shell's own ``<script src>`` assets in page order and stops at the
    first one that contains the API root.
    """
    for page in bundles:
        if API_ROOT in page.content:
            return page
    return None


class SscacVenueSource(PublicAccessSource):
    source_id = 'venue-suzhou-arts'
    source_name = 'Suzhou Culture and Arts Centre'
    kind = 'venue'
    source_url = BASE_URL + ENTRY_PATH
    crawl_url = BASE_URL + ENTRY_PATH
    extractor = 'sscac_performance'

    @staticmethod
    def is_public_url(url):
        """Approved routes only: HTTPS, same host, no query, no credentials, no fragment."""
        parts = urlparse(url)
        return (
            parts.scheme == 'https'
            and parts.hostname == HOST
            and parts.port in (None, 443)
            and parts.username is None
            and parts.password is None
            and not parts.query
            and not parts.fragment
            and (parts.path in (ENTRY_PATH, LISTING_PATH)
                 or BUNDLE_PATH.fullmatch(parts.path) is not None
                 or parts.path in ENDPOINTS)
        )

    def collect(self):
        items = []
        today = local_today()
        self.investigation = {
            'scope': 'client-rendered shell read through the JSON endpoint its own JS calls',
            'api_root': BASE_URL + API_ROOT,
            'endpoints': {},
            'endpoint_discovered_in_published_bundle': False,
            'bundle_assets_skipped': [],
            'records_seen': 0,
            'records_available': 0,
            'records_selected': 0,
            'records_rejected': [],
            'pages_requested': 0,
            'credentials_used': 0,
        }
        try:
            listing = self.public_page(BASE_URL + LISTING_PATH)
        except Exception as exc:
            self.errors.append({'url': BASE_URL + LISTING_PATH, 'error': str(exc)})
            return [*self.policy_items, *items]
        items.append(self.item(listing, key='sscac-listing-context', is_event=False,
                               extractor='context'))
        title = re.search(r'<title[^>]*>([^<]{1,200})</title>', listing.content, re.I)
        if not title or TITLE_MARKER not in title.group(1):
            self.errors.append({
                'url': listing.url,
                'error': 'Served page no longer identifies itself as ' + TITLE_MARKER +
                         ' (title check failed); no JSON request made',
            })
            return [*self.policy_items, *items]

        bundles = []
        skipped = []
        for href in SCRIPT_SRC.findall(listing.content)[:6]:
            url = urljoin(listing.url, href)
            if BUNDLE_PATH.fullmatch(urlparse(url).path or '') is None:
                continue
            try:
                page = self.public_page(url, media=JS_MEDIA)
            except Exception as exc:
                # An asset that cannot be read (typically a vendor bundle past the 2 MB
                # prototype cap) is simply not the entry point; the skip is recorded so it is
                # never silent, and the source still fails closed below when NOTHING advertises
                # the API.
                skipped.append({'url': url, 'error': str(exc)})
                continue
            bundles.append(page)
            if API_ROOT in page.content:
                break  # assets after the one that advertises the API are irrelevant
        self.investigation['bundle_assets_skipped'] = skipped
        discovery = published_endpoint_bundle(bundles)
        if discovery is None:
            self.errors.append({
                'url': listing.url,
                'error': 'The host\'s own published JavaScript no longer advertises ' +
                         API_ROOT + '; the API route is never assumed, so no JSON request '
                         'was made',
            })
            return [*self.policy_items, *items]
        self.investigation['endpoint_discovered_in_published_bundle'] = True
        self.investigation['endpoint_bundle'] = discovery.url
        items.append(self.item(discovery, key='sscac-js-endpoint-discovery', is_event=False,
                               extractor='context'))

        merged = {}
        order = []
        for endpoint in ENDPOINTS:
            url = BASE_URL + endpoint
            stats = {'pages': 0, 'records': 0, 'kept': 0, 'error': None}
            self.investigation['endpoints'][endpoint] = stats
            for page_number in range(1, MAX_PAGES + 1):
                body = request_body(endpoint, page_number, today)
                try:
                    page = self.public_json(url, method='POST', json_body=body)
                except Exception as exc:
                    stats['error'] = str(exc)
                    self.errors.append({'url': url, 'error': str(exc)})
                    break
                stats['pages'] += 1
                self.investigation['pages_requested'] += 1
                if page_number == 1:
                    items.append(self.item(
                        page, key='sscac-context-' + endpoint.rsplit('/', 1)[-1],
                        is_event=False, extractor='context'))
                try:
                    document = json.loads(page.content)
                except ValueError as exc:
                    stats['error'] = 'response is not JSON: ' + str(exc)
                    self.errors.append({'url': url, 'error': stats['error']})
                    break
                if not is_envelope_ok(document):
                    stats['error'] = ('response envelope is not the documented success shape '
                                      '(code/obj.records); no event is published from it')
                    self.errors.append({'url': url, 'error': stats['error']})
                    break
                rows = document['obj']['records']
                stats['records'] += len(rows)
                self.investigation['records_seen'] += len(rows)
                for record in rows:
                    keep, reason = record_is_usable(record)
                    if not keep:
                        self.investigation['records_rejected'].append(
                            {'endpoint': endpoint, 'id': str((record or {}).get('id'))[:40],
                             'reason': reason})
                        continue
                    key = str(record['id'])
                    if key in merged:
                        continue  # both public lists carry the same programme; the id is it
                    finished = (record_date(record.get('projectEndTime'))
                                or record_date(record['projectStartTime']))
                    if finished and date.fromisoformat(finished) < today:
                        self.investigation['records_rejected'].append(
                            {'endpoint': endpoint, 'id': key,
                             'reason': 'performance finished before ' + today.isoformat() +
                                       '; the historical archive is not republished'})
                        continue
                    merged[key] = (endpoint, page, record)
                    order.append(key)
                if len(rows) < PAGE_SIZE:
                    break
            stats['kept'] = sum(1 for key in order if merged[key][0] == endpoint)
        if not order:
            self.errors.append({
                'url': BASE_URL + YANYI_PATH,
                'error': 'No upcoming performance record passed the source field checks; the '
                         'raw responses are retained and no event is invented',
            })
            return [*self.policy_items, *items]

        selected = sorted(
            order,
            key=lambda key: (record_date(merged[key][2].get('projectStartTime')) or '', key),
        )[:self.max_items]
        for key in selected:
            _, page, record = merged[key]
            items.append(self.item(page, key='sscac-' + key, extractor=self.extractor,
                                   locator=key, raw=json.dumps(record, ensure_ascii=False)))
        self.investigation['records_available'] = len(order)
        self.investigation['records_selected'] = len(selected)
        return [*self.policy_items, *items]


def sscac_performance(item):
    """Deterministic extraction for one performance record (the API's own object).

    Only explicit fields are read: ``projectName``, ``projectStartTime``/``projectEndTime``,
    ``projectTypeId``, ``siteName`` and ``projectCompany``. The venue is the official host's
    own identity, which ``collect`` verifies from the served page title before any record is
    emitted; the published hall (``siteName``) is recorded as the location instead of being
    rewritten into a venue name.
    """
    try:
        record = json.loads(item.raw_content)
    except ValueError as exc:
        raise ValueError('SSCAC record is not the JSON object it was served as: ' + str(exc))
    if not isinstance(record, dict):
        raise ValueError('SSCAC record is not a JSON object')
    if str(record.get('id')) != str(item.locator):
        raise ValueError('SSCAC record id does not match the collected item')
    keep, reason = record_is_usable(record)
    if not keep:
        raise ValueError('SSCAC record rejected: ' + reason)
    start = record_date(record['projectStartTime'])
    finish = record_date(record.get('projectEndTime'))
    if finish and finish < start:
        raise ValueError('SSCAC end date precedes the start date; interval rejected')
    name = text(record['projectName'])
    event = base(item)
    set_field(event, 'event_name', name, snippet='projectName=' + name, confidence=0.9,
              method='explicit_source_projectName_field')
    set_field(event, 'start_date', start,
              snippet='projectStartTime=' + str(record.get('projectStartTime')),
              confidence=0.9, method='explicit_source_performance_start_datetime')
    if finish:
        set_field(event, 'end_date', finish,
                  snippet='projectEndTime=' + str(record.get('projectEndTime')),
                  confidence=0.9, method='explicit_source_performance_end_datetime')
    hall = text(record.get('siteName'))
    set_field(event, 'venue', VENUE_NAME,
              snippet='official host ' + HOST + ' = ' + VENUE_NAME +
                      ' (page title check in collect)',
              confidence=0.85, method='official_venue_host_identity_of_the_registry_source')
    set_field(event, 'location', hall,
              snippet='siteName=' + str(hall),
              confidence=0.7,
              method='explicit_source_siteName_field (published hall, not street-address '
                     'enrichment)')
    organizer = text(record.get('projectCompany'))
    set_field(event, 'organizer', organizer, snippet='projectCompany=' + str(organizer),
              confidence=0.8)
    performance_type = text(record.get('projectTypeId'))
    category = ('culture'
                if performance_type and PERFORMANCE_TYPE.search(performance_type)
                else 'others')
    set_field(event, 'category', category,
              snippet='projectTypeId=' + str(performance_type), confidence=0.6,
              status='Needs Review', method='source_published_projectTypeId_keyword_rule')
    return event
