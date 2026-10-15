"""苏州国际博览中心 (Suzhou International Expo Centre) exhibition calendar — public JSON API.

Why this source changed on 2026-10-15
-------------------------------------
The V1.6 reconnaissance recorded ``www.suzhouexpo.com`` as BLOCKED: the schedule page is
server-rendered but near-empty (197 visible characters), carries no date anywhere, and
mentions ``token``/``Authorization``. The V1.6.2 verdict was "No static schedule exists; the
dynamic token-header APIs are out of scope", and the adapter was an audit-only handler that
counted those token references without ever calling the API.

The page is not empty — it is a Vue application, and the schedule is assembled in the browser
from the site's own public JSON. Read live that way (TLS verification on, no credential of
any kind, robots permissive: ``/robots.txt`` answers 404):

  * ``GET /zhanhuiricheng-389.html`` -> 200, and its own inline script declares
    ``url: config.host_url + '/api/Article/list'`` with ``headers: {'Access-Token': config.token}``
    and ``data: {cate_id: 389, is_sub: 0}``. The route approval in this module is derived
    from that published markup, not from a hard-coded guess.
  * ``GET /templates/expo_CN/js/config.js`` -> 200: ``var config = {token: 'fyxmt', ...}``.
    That constant is shipped to every browser as part of the public page; it is a channel
    identifier for this site's read-only JSON, not a user credential and not a login. It is
    read from the host's own file on every run and never written down here.
  * ``GET /api/Catogery/sub_list?cate_id=389&is_sub=0`` (with that header) -> 200 JSON,
    ``success:true``, the exhibition year categories (2026, 2025, ... 2017).
  * ``GET /api/Article/list?cate_id=434&...`` -> 200 JSON, ``totalItems: 51`` for 2026, every
    record carrying ``title`` and ``extras.start_time``/``extras.end_time``. Six were still
    upcoming on 2026-10-15 (NVIDIA会议 2026-10-15, 纳博会 2026-10-21, 金蜘蛛苏州紧固件与技术展
    2026-10-21, 第35届中国厨师节 2026-10-22, 第三十三届中国汽车工程学会年会 2026-10-27,
    TestConX China 2026半导体会议 2026-10-29).

Boundaries kept, explicitly:

  * the token and the category id are read from the host's own published page/config, and the
    source fails closed with a recorded reason when either stops advertising them;
  * only the current and next year categories are requested, at most ``MAX_PAGES`` pages each,
    because the endpoint also serves every past year;
  * ``extras.start_time`` carries a clock that is the CMS insertion time (``add_time``
    15:57:13Z vs ``start_time`` 2026-01-30T15:57:01 - same clock, edited date), so only the
    calendar date is ever published, exactly the value the venue's own page renders with
    ``moment(start_time).format('MM月DD日')``;
  * a finished exhibition is skipped with a recorded reason instead of being republished.

Item contract: an event item's raw content is that record's own JSON object exactly as the API
served it; the year-category response is retained once as a context item.
"""

import json
import re
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode, urlparse

from crawler.extractor import base, full_date, set_field, text
from crawler.sources.event_platform.public_access import PublicAccessSource

HOST = 'www.suzhouexpo.com'
BASE_URL = 'https://' + HOST
# The registry's crawl URL; the page that publishes the schedule's own request contract.
SCHEDULE_PATH = '/zhanhuiricheng-389.html'
HOME_PATH = '/index.aspx'
CONFIG_PATH = '/templates/expo_CN/js/config.js'
CATEGORY_PATH = '/api/Catogery/sub_list'
ARTICLE_PATH = '/api/Article/list'
API_PATHS = (CATEGORY_PATH, ARTICLE_PATH)
# Read from the page's own inline script / the site's own config.js; never assumed.
CATEGORY_ID = re.compile(r'cate_id\s*:\s*(\d{1,6})')
PUBLIC_TOKEN = re.compile(r'token\s*:\s*[\'"]([^\'"\s]{1,64})[\'"]')
YEAR_TITLE = re.compile(r'^(20\d{2})$')
# The site's own config file is served as application/javascript (sometimes text/plain).
JS_MEDIA = ('javascript', 'text/plain')
# The venue's own identity: this host is 苏州国际博览中心's official site, and the served
# schedule page must still say so (checked in collect()).
VENUE_NAME = '苏州国际博览中心'
TITLE_MARKER = '苏州国际博览中心'
LOCAL_TIMEZONE = timezone(timedelta(hours=8))
PAGE_SIZE = 100
MAX_PAGES = 2
MAX_CATEGORIES = 2
# Explicit keyword evidence from the record's own published title; anything else is 'others'.
CULTURE_TITLE = re.compile(r'文创|文化|艺术|书画|非遗|博物馆|美术|摄影|动漫|图书|佛事|佛文化')
BUSINESS_TITLE = re.compile(
    r'展览会|博览会|交易会|展销会|展会|展览|产业展|年会|论坛|峰会|大会|会议|采购会|订货会'
)


def local_today():
    """The calendar's own local day (Asia/Shanghai), used only to skip finished fairs."""
    return datetime.now(LOCAL_TIMEZONE).date()


def schedule_contract(page_html):
    """``(category_id, config_path)`` declared by the schedule page's own published markup."""
    category = CATEGORY_ID.search(page_html)
    config = CONFIG_PATH if CONFIG_PATH in page_html else None
    return (category[1] if category else None), config


def public_token(config_js):
    """The static channel token the site publishes in its own config.js, else None."""
    matched = PUBLIC_TOKEN.search(config_js or '')
    return matched[1] if matched else None


def is_success(document):
    """True only for this API's own success envelope."""
    return isinstance(document, dict) and document.get('success') is True


def year_categories(document, today):
    """``[(category_id, year)]`` for the current and following years only, in API order."""
    rows = document.get('data')
    if not isinstance(rows, list):
        return []
    selected = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = text(str(row.get('title') or ''))
        matched = YEAR_TITLE.fullmatch(title or '')
        if not matched or row.get('id') in (None, ''):
            continue
        year = int(matched[1])
        if today.year <= year <= today.year + 1:
            selected.append((str(row['id']), year))
    return selected[:MAX_CATEGORIES]


def article_rows(document):
    """The records of one ``/api/Article/list`` response, or None when the shape changed."""
    data = document.get('data')
    if not isinstance(data, dict) or not isinstance(data.get('items'), list):
        return None
    return data['items']


def record_date(value):
    """``YYYY-MM-DD`` of an explicit start/end value, else None (never a partial date)."""
    return full_date(value) if isinstance(value, str) else None


def record_is_usable(record):
    """``(keep, reason)`` for one exhibition record, judged only on explicit fields."""
    if not isinstance(record, dict):
        return False, 'record is not a JSON object'
    if not text(record.get('title')):
        return False, 'record carries no title'
    extras = record.get('extras')
    if not isinstance(extras, dict):
        return False, 'record carries no extras object'
    if record_date(extras.get('start_time')) is None:
        return False, ('record carries no complete YYYY-MM-DD extras.start_time (value=' +
                       str(extras.get('start_time'))[:40] + ')')
    return True, None


def title_category(name):
    """Category only on explicit title evidence; otherwise the schema default 'others'."""
    for category, pattern, evidence in (
        ('culture', CULTURE_TITLE, 'title contains an explicit cultural-event keyword'),
        ('business', BUSINESS_TITLE, 'title contains an explicit exhibition/trade-fair keyword'),
    ):
        matched = pattern.search(name)
        if matched:
            return category, evidence + '=' + matched[0]
    return 'others', 'no explicit business/culture keyword in the published title (default)'


class ExpoVenueSource(PublicAccessSource):
    source_id = 'venue-suzhou-expo'
    source_name = '苏州国际博览中心官方展会日程'
    kind = 'venue'
    source_url = BASE_URL + '/'
    crawl_url = BASE_URL + SCHEDULE_PATH
    extractor = 'expo_exhibition'

    @staticmethod
    def is_public_url(url):
        """Approved routes only: HTTPS, same host, no credentials, no fragment.

        The two JSON endpoints are the only routes that may carry a query string; the pages
        and the published config file are path-only.
        """
        parts = urlparse(url)
        if (parts.scheme != 'https' or parts.hostname != HOST or parts.port not in (None, 443)
                or parts.username is not None or parts.password is not None or parts.fragment):
            return False
        if parts.path in API_PATHS:
            return True
        return parts.path in (SCHEDULE_PATH, HOME_PATH, CONFIG_PATH) and not parts.query

    def collect(self):
        items = []
        today = local_today()
        self.investigation = {
            'scope': 'Vue schedule page read through the public JSON its own script calls',
            'request_contract': 'derived from the schedule page\'s own inline script, not assumed',
            'static_channel_token': 'read from the host\'s own public config.js; not a credential',
            'categories_seen': 0,
            'categories_requested': [],
            'records_seen': 0,
            'records_available': 0,
            'records_selected': 0,
            'records_rejected': [],
            'pages_requested': 0,
            'credentials_used': 0,
        }
        try:
            schedule = self.public_page(BASE_URL + SCHEDULE_PATH)
        except Exception as exc:
            self.errors.append({'url': BASE_URL + SCHEDULE_PATH, 'error': str(exc)})
            return [*self.policy_items, *items]
        items.append(self.item(schedule, key='expo-schedule-context', is_event=False,
                               extractor='context'))
        title = re.search(r'<title[^>]*>([^<]{1,200})</title>', schedule.content, re.I)
        if not title or TITLE_MARKER not in title.group(1):
            self.errors.append({
                'url': schedule.url,
                'error': 'Served page no longer identifies itself as ' + TITLE_MARKER +
                         ' (title check failed); no JSON request made',
            })
            return [*self.policy_items, *items]
        category_id, config_path = schedule_contract(schedule.content)
        if not category_id or not config_path or ARTICLE_PATH not in schedule.content:
            self.errors.append({
                'url': schedule.url,
                'error': 'The schedule page no longer publishes its own JSON contract '
                         '(cate_id / ' + ARTICLE_PATH + ' / ' + CONFIG_PATH +
                         '); the routes are never assumed, so no JSON request was made',
            })
            return [*self.policy_items, *items]

        try:
            config = self.public_page(BASE_URL + config_path, media=JS_MEDIA)
        except Exception as exc:
            self.errors.append({'url': BASE_URL + config_path, 'error': str(exc)})
            return [*self.policy_items, *items]
        items.append(self.item(config, key='expo-public-config', is_event=False,
                               extractor='context'))
        token = public_token(config.content)
        if not token:
            self.errors.append({
                'url': config.url,
                'error': 'The host\'s own public config.js no longer publishes its static '
                         'channel token; no JSON request was made',
            })
            return [*self.policy_items, *items]
        headers = {'Access-Token': token}

        try:
            categories_url = (BASE_URL + CATEGORY_PATH + '?' +
                              urlencode({'cate_id': category_id, 'is_sub': 0}))
            categories_page = self.public_json(categories_url, headers=headers)
        except Exception as exc:
            self.errors.append({'url': BASE_URL + CATEGORY_PATH, 'error': str(exc)})
            return [*self.policy_items, *items]
        items.append(self.item(categories_page, key='expo-categories-context', is_event=False,
                               extractor='context'))
        try:
            categories_document = json.loads(categories_page.content)
        except ValueError as exc:
            self.errors.append({'url': categories_page.url,
                                'error': 'category response is not JSON: ' + str(exc)})
            return [*self.policy_items, *items]
        if not is_success(categories_document):
            self.errors.append({
                'url': categories_page.url,
                'error': 'category response is not the documented success envelope; no event '
                         'is published from it',
            })
            return [*self.policy_items, *items]
        categories = year_categories(categories_document, today)
        self.investigation['categories_seen'] = len(categories_document.get('data') or [])
        if not categories:
            self.errors.append({
                'url': categories_page.url,
                'error': 'No exhibition year category for ' + str(today.year) + '/' +
                         str(today.year + 1) + ' is published; the past archive is never '
                         'republished as live demand',
            })
            return [*self.policy_items, *items]

        merged = {}
        order = []
        for year_id, year in categories:
            self.investigation['categories_requested'].append({'id': year_id, 'year': year})
            for page_number in range(1, MAX_PAGES + 1):
                params = {
                    'cate_id': year_id, 'is_sub': 'true', 'albums': 'true', 'attachs': 'true',
                    'pageIndex': page_number, 'pageSize': PAGE_SIZE,
                    'sort': 'start_time asc', 'search_params': '',
                }
                url = BASE_URL + ARTICLE_PATH + '?' + urlencode(params)
                try:
                    page = self.public_json(url, headers=headers)
                except Exception as exc:
                    self.errors.append({'url': url, 'error': str(exc)})
                    break
                self.investigation['pages_requested'] += 1
                if page_number == 1:
                    items.append(self.item(page, key='expo-context-' + str(year),
                                           is_event=False, extractor='context'))
                try:
                    document = json.loads(page.content)
                except ValueError as exc:
                    self.errors.append({'url': page.url,
                                        'error': 'list response is not JSON: ' + str(exc)})
                    break
                if not is_success(document):
                    self.errors.append({
                        'url': page.url,
                        'error': 'list response is not the documented success envelope; no '
                                 'event is published from it',
                    })
                    break
                rows = article_rows(document)
                if rows is None:
                    self.errors.append({
                        'url': page.url,
                        'error': 'list response no longer carries data.items; no event is '
                                 'published from it',
                    })
                    break
                self.investigation['records_seen'] += len(rows)
                for record in rows:
                    keep, reason = record_is_usable(record)
                    if not keep:
                        self.investigation['records_rejected'].append(
                            {'id': str((record or {}).get('id'))[:40], 'reason': reason})
                        continue
                    key = str(record['id'])
                    if key in merged:
                        continue
                    extras = record['extras']
                    finished = (record_date(extras.get('end_time'))
                                or record_date(extras['start_time']))
                    if finished and date.fromisoformat(finished) < today:
                        self.investigation['records_rejected'].append(
                            {'id': key,
                             'reason': 'exhibition finished before ' + today.isoformat() +
                                       '; the year archive is not republished'})
                        continue
                    merged[key] = (page, record)
                    order.append(key)
                if len(rows) < PAGE_SIZE:
                    break
        if not order:
            self.errors.append({
                'url': BASE_URL + ARTICLE_PATH,
                'error': 'No upcoming exhibition record passed the source field checks; the raw '
                         'responses are retained and no event is invented',
            })
            return [*self.policy_items, *items]

        selected = sorted(
            order,
            key=lambda key: (record_date(merged[key][1]['extras'].get('start_time')) or '', key),
        )[:self.max_items]
        for key in selected:
            page, record = merged[key]
            items.append(self.item(page, key='expo-' + key, extractor=self.extractor,
                                   locator=key, raw=json.dumps(record, ensure_ascii=False)))
        self.investigation['records_available'] = len(order)
        self.investigation['records_selected'] = len(selected)
        return [*self.policy_items, *items]


def expo_exhibition(item):
    """Deterministic extraction for one exhibition record (the API's own object).

    Only explicit fields are read: ``title`` and ``extras.start_time``/``extras.end_time``.
    The clock inside ``extras.start_time`` is the CMS insertion time, so only its calendar
    date is published — the same value the venue's own page renders. The venue is the host's
    own identity, verified by the title check in ``collect`` before any record is emitted.
    """
    try:
        record = json.loads(item.raw_content)
    except ValueError as exc:
        raise ValueError('Expo record is not the JSON object it was served as: ' + str(exc))
    if not isinstance(record, dict):
        raise ValueError('Expo record is not a JSON object')
    if str(record.get('id')) != str(item.locator):
        raise ValueError('Expo record id does not match the collected item')
    keep, reason = record_is_usable(record)
    if not keep:
        raise ValueError('Expo record rejected: ' + reason)
    extras = record['extras']
    start = record_date(extras['start_time'])
    finish = record_date(extras.get('end_time'))
    if finish and finish < start:
        raise ValueError('Expo end date precedes the start date; interval rejected')
    name = text(record['title'])
    event = base(item)
    set_field(event, 'event_name', name, snippet='title=' + name, confidence=0.9,
              method='explicit_source_title_field')
    set_field(event, 'start_date', start,
              snippet='extras.start_time=' + str(extras.get('start_time')) +
                      ' (calendar date only; the published clock is the CMS insertion time)',
              confidence=0.9, method='explicit_source_exhibition_start_datetime')
    if finish:
        set_field(event, 'end_date', finish,
                  snippet='extras.end_time=' + str(extras.get('end_time')) +
                          ' (calendar date only; the published clock is the CMS insertion time)',
                  confidence=0.9, method='explicit_source_exhibition_end_datetime')
    set_field(event, 'venue', VENUE_NAME,
              snippet='official host ' + HOST + ' = ' + VENUE_NAME +
                      ' (page title check in collect)',
              confidence=0.85, method='official_venue_host_identity_of_the_registry_source')
    organizer = text(extras.get('organizer'))
    set_field(event, 'organizer', organizer, snippet='extras.organizer=' + str(organizer),
              confidence=0.8)
    category, why = title_category(name)
    set_field(event, 'category', category, snippet=why + ' | title=' + name, confidence=0.6,
              status='Needs Review', method='event_title_published_keyword_rule')
    return event
