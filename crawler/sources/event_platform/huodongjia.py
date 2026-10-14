"""Huodongjia (活动家) adapter over its server-rendered ``__NEXT_DATA__`` payload.

Ground truth verified on the public site: the city route ``/suzhou`` is a JS-only
shell with no dates, but the HOMEPAGE and the ``/event-<uuid>.html`` detail pages
are server-rendered and embed real event records in
``<script id="__NEXT_DATA__">`` at ``props.pageProps.initialData``.

Only public GET is used: no login, token, signing, app endpoint or CAPTCHA path.
Discovery and publication are separated on purpose - the homepage payload supplies
candidate detail URLs (with the source's own ``city_name``/``province_name``), and
only records the source itself places in Suzhou are ever requested or published.
A wrong-city record is rejected before a detail request is made, and a detail page
is re-checked against its own ``city_name``/``province_name`` after fetching.

Dates come from explicit ``begin_time``/``end_time`` only. Publication dates, sale
prices, ticket times and years written inside a title are never substituted.
"""
import html
import json
import re
from datetime import date, datetime
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from crawler.extractor import base, label_organizer, set_field, text
from .public_access import PublicAccessSource, blocked_page, public_https

HOST = 'www.huodongjia.com'
HOME_URL = 'https://' + HOST + '/'
DETAIL_PATH = re.compile(r'^/event-(\d{1,32})\.html$')
# The visible anchor/href form uses the same opaque numeric event UUID as the payload.
EVENT_UUID = re.compile(r'^\d{1,32}$')
# Suzhou City, Jiangsu. The bare city name is the source's own city_name value.
SUZHOU_CITIES = {'苏州', '苏州市', 'suzhou', 'suzhou city'}
SUZHOU_PROVINCES = {'江苏省', '江苏', 'jiangsu'}
# Placeholder labels the platform writes when it holds no real organiser name.
PLACEHOLDER_ORGANIZERS = ('主办方', '活动家', '组委会', '主办单位', '承办单位', '协办单位')
# Where a labelled value in the description ends. The description is flattened before
# matching, so a following label word or a sentence boundary terminates the value.
LABEL_HEADS = (r'(?:尊敬|嘉宾|时间|地点|会议地点|活动地点|举办地点|主办|主办方|主办单位|协办|承办|'
               r'指导|支持|赞助|参会|报名|由)\s*[:：]?')
ORGANIZER_LABEL = re.compile(
    r'(?:主办单位|主办方|主办机构)\s*[:：]\s*([^\n]{2,80}?)'
    r'(?=' + LABEL_HEADS + r'|\s{2,}|\n|$)'
)
ORGANIZER_SENTENCE = re.compile(r'由([^，,。;\n]{2,60}?)主办')
VENUE_LABEL = re.compile(
    r'(?:会议地点|活动地点|举办地点|地点|场馆)\s*[:：]\s*'
    r'([^，,。;；\n]{2,60}?)'
    r'(?=' + LABEL_HEADS + r'|\s{2,}|\n|$)'
)
CANCELLED = re.compile(r'cancel|取消')

# The source publishes technology/business/medical/training topics. Anything not
# mapped here still needs explicit keyword evidence before it leaves 'others'.
TOPIC_CATEGORIES = {
    'it': 'business', 'rengongzhineng': 'business', 'dashuju': 'business',
    'wulianwang': 'business', 'yunwei': 'business', 'wangluoanquan': 'business',
    'shenduxuexi': 'business', 'jiagou': 'business', 'qukuailian': 'business',
    'finance': 'business', 'tourongzi': 'business', 'yinhang': 'business',
    'gongyinglianjinrong': 'business', 'reits': 'business', 'qiyejia': 'business',
    'baoxian': 'business',
    'medical': 'business', 'jiankangchanye': 'business', 'yiyao': 'business',
    'jingzhunyiliao': 'business', 'xunzhengyixue': 'business', 'scilunwen': 'business',
    'wangluoyaolixue': 'business', 'jiyinbianji': 'business', 'zhongliu': 'business',
    'edutrain': 'education', 'jiaoshi': 'education', 'zaixianjiaoyu': 'education',
    'rencaipeiyang': 'education', 'chuangxinjiaoyu': 'education', 'youjiao': 'education',
    'xiaozhang': 'education', 'gaoxiao': 'education',
    'sports': 'sports', 'saishi': 'sports', 'ticao': 'sports',
    'gov': 'government', 'zhengfu': 'government', 'zhengwu': 'government',
    'culture': 'culture', 'wenhua': 'culture', 'yishu': 'culture', 'yinyue': 'culture',
    'minsu': 'folk', 'feiyi': 'folk', 'chuantong': 'folk',
}
NAME_CATEGORY_RULES = (
    ('sports', re.compile(r'足球|篮球|网球|马拉松|比赛|赛事|竞速|体育|运动|电竞')),
    ('government', re.compile(r'政府|政务|政策|公共|乡村振兴|党建')),
    ('folk', re.compile(r'民俗|非遗|庙会|灯会|传统|民间')),
    ('education', re.compile(r'讲座|培训|研学|论坛|峰会|公开课|研讨会|学术会议|教育')),
    ('business', re.compile(r'博览会|交易会|展销|招商|投资|产业大会|行业大会|峰会|年会|大会|论坛|展览|展会')),
)


def next_data(content):
    """Return the page's ``__NEXT_DATA__`` JSON payload, or fail closed."""
    soup = BeautifulSoup(content, 'html.parser')
    node = soup.select_one('script#__NEXT_DATA__')
    if node is None:
        raise ValueError(
            'Huodongjia page is no longer server-rendered with __NEXT_DATA__; '
            'no event data is published from an unverified page state'
        )
    try:
        document = json.loads(node.get_text())
    except json.JSONDecodeError as exc:
        raise ValueError('Huodongjia __NEXT_DATA__ payload is not valid JSON: ' + str(exc))
    if not isinstance(document, dict):
        raise ValueError('Huodongjia __NEXT_DATA__ payload has an unsupported structure')
    return document


def page_props(document):
    props = document.get('props')
    props = props.get('pageProps') if isinstance(props, dict) else None
    if not isinstance(props, dict):
        raise ValueError('Huodongjia __NEXT_DATA__ has no props.pageProps payload')
    return props


def payload_date(value):
    """Return ``YYYY-MM-DD`` for an explicit source datetime, else None.

    Only the source's own complete ``YYYY-MM-DD[ HH:MM[:SS]]`` values qualify;
    relative, partial or publication-style values never become an event date.
    """
    if not isinstance(value, str):
        return None
    matched = re.fullmatch(r'(\d{4}-\d{2}-\d{2})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?', value.strip())
    if not matched:
        return None
    try:
        return date.fromisoformat(matched[1]).isoformat()
    except ValueError:
        return None


def as_text(value):
    if not isinstance(value, str):
        return None
    return text(value)


def is_suzhou(city, province=None):
    """True only when the source itself places the record in Suzhou."""
    city_text = (city or '').strip()
    if city_text.casefold() not in SUZHOU_CITIES:
        return False
    if province is None or not str(province).strip():
        return True
    return str(province).strip() in SUZHOU_PROVINCES


def candidate_detail_url(uuid):
    """Build the canonical detail URL for one payload event UUID, else None."""
    value = str(uuid)
    if not EVENT_UUID.fullmatch(value):
        return None
    return HOME_URL + 'event-' + value + '.html'


def homepage_records(content):
    """Candidate records from the homepage SSR payload, in payload order.

    The whole ``initialData`` tree is walked at any depth, so every ``events[]`` list
    under every ``children[]`` node is covered. The live payload repeats the same events
    across category groups (66 event objects for 21 distinct events on 2026-10-13), so
    records are de-duplicated by ``event_uuid`` with the first occurrence winning. The
    walk is iterative: no recursion limit can silently truncate discovery.
    """
    document = next_data(content)
    initial = page_props(document).get('initialData')
    if not isinstance(initial, list) or not initial:
        raise ValueError('Huodongjia homepage SSR payload contains no category event groups')
    records = []
    seen = set()
    stack = [initial]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            uuid = node.get('event_uuid')
            if uuid is not None and str(uuid) not in seen:
                seen.add(str(uuid))
                records.append(node)
            stack.extend(reversed(list(node.values())))
        elif isinstance(node, list):
            stack.extend(reversed(node))
    if not records:
        raise ValueError('Huodongjia homepage SSR payload contains no event records')
    return records


def anchor_candidates(content):
    """Fallback discovery from ``<a href="/event-*.html">`` links in the HTML."""
    found = []
    for node in BeautifulSoup(content, 'html.parser').select('a[href]'):
        parts = urlparse(node['href'])
        if parts.scheme or parts.netloc or parts.query or parts.fragment:
            continue
        matched = DETAIL_PATH.fullmatch(parts.path)
        if matched and matched[1] not in found:
            found.append(matched[1])
    return found


def event_page(payload, url):
    """Validate one fetched detail page and return its ``initialData`` record."""
    if not HuodongjiaSource.is_public_url(url) or not DETAIL_PATH.fullmatch(urlparse(url).path):
        raise ValueError('Huodongjia event data must come from an approved public detail page')
    initial = payload.get('initialData')
    if not isinstance(initial, dict):
        raise ValueError('Huodongjia detail page has no structured initialData record')
    uuid = str(initial.get('event_uuid') or '')
    expected = DETAIL_PATH.fullmatch(urlparse(url).path)[1]
    if uuid != expected:
        raise ValueError('Detail page event UUID does not match the requested public item')
    return initial


def organizer_from(initial, description):
    """Explicit organiser evidence only; the platform placeholder is not a name."""
    labelled = initial.get('organizer')
    if isinstance(labelled, dict):
        name = text(labelled.get('name')) if isinstance(labelled.get('name'), str) else None
    else:
        name = text(labelled) if isinstance(labelled, str) else None
    stripped = re.sub(r'\s+', '', name or '')
    if name and not any(word in stripped for word in PLACEHOLDER_ORGANIZERS):
        return name, 'SSR.organizer.name=' + json.dumps(labelled, ensure_ascii=False)
    matched = ORGANIZER_LABEL.search(description)
    if not matched:
        matched = ORGANIZER_SENTENCE.search(description)
    if not matched:
        return None, None
    return trim_label(matched[1]), matched[0]


def trim_label(value):
    """Cut a labelled value at the next label word the description may follow it with."""
    if not value:
        return value
    return re.split(r'\s*' + LABEL_HEADS, value)[0].strip()


def venue_from(description):
    """Explicit labelled venue in the description; never a template or a guess."""
    for matched in VENUE_LABEL.finditer(description):
        value = trim_label(matched[1].strip())
        if '苏州' in value and not re.search(r'酒店预订|在线报名|立即报名', value):
            return value, matched[0].strip()
    return None, None


def topic_category(slug, label):
    """Map the source's own topic vocabulary onto the schema categories."""
    key = (slug or '').strip().casefold()
    if key and key in TOPIC_CATEGORIES:
        return TOPIC_CATEGORIES[key], 'source_topic_slug=' + key
    label = label or ''
    if re.search(r'体育|运动|赛事', label):
        return 'sports', 'source_topic_label=' + label
    if re.search(r'政务|政府|公共', label):
        return 'government', 'source_topic_label=' + label
    if re.search(r'民俗|非遗|传统', label):
        return 'folk', 'source_topic_label=' + label
    if re.search(r'教育|培训', label):
        return 'education', 'source_topic_label=' + label
    if re.search(r'金融|财经|医疗|医学|互联网|科技|商业|会展', label):
        return 'business', 'source_topic_label=' + label
    return None, None


def name_category(name):
    for category, pattern in NAME_CATEGORY_RULES:
        if pattern.search(name):
            return category
    return 'others'


def huodongjia_event(item):
    """Deterministic extraction for one server-rendered Huodongjia detail page."""
    if blocked_page(item.raw_content):
        raise ValueError('Login/CAPTCHA/access wall: raw retained, no event published')
    document = next_data(item.raw_content)
    initial = event_page(page_props(document), item.original_url)

    name = as_text(initial.get('event_name'))
    if not name:
        raise ValueError('Huodongjia detail page has no explicit event name')
    if item.locator and str(initial.get('event_uuid')) != str(item.locator):
        raise ValueError('Detail page event UUID does not match the collected item locator')

    # Explicit source datetimes only; sale/price/ticket values are never dates.
    start = payload_date(initial.get('begin_time'))
    if not start:
        raise ValueError(
            'No explicit Huodongjia begin_time; publication/sale dates and title years '
            'are not substituted'
        )
    finish = None
    if initial.get('end_time') is not None:
        finish = payload_date(initial.get('end_time'))
        if not finish:
            raise ValueError('Huodongjia end_time cannot be reliably parsed')
        if finish < start:
            raise ValueError('Huodongjia end_time precedes begin_time; interval rejected')

    city = as_text(initial.get('city_name'))
    province = as_text(initial.get('province_name'))
    if not is_suzhou(city, province):
        raise ValueError(
            'Explicit Suzhou city/province required; source record is '
            + repr(city) + '/' + repr(province) + '; wrong-city records are never published'
        )

    status = as_text(initial.get('status')) or ''
    if CANCELLED.search(status) or CANCELLED.search(name):
        raise ValueError('Cancelled event: raw retained, not published')

    description = BeautifulSoup(
        html.unescape(initial.get('description') or ''), 'html.parser'
    ).get_text('\n', strip=True)
    raw_description = re.sub(r'\n+', ' ', description)

    event = base(item)
    set_field(event, 'event_name', name,
              snippet='SSR.initialData.event_name=' + name, confidence=0.9)
    set_field(event, 'start_date', start,
              snippet='SSR.initialData.begin_time=' + str(initial.get('begin_time')),
              confidence=0.9, method='explicit_source_event_datetime (not sale time)')
    if finish:
        set_field(event, 'end_date', finish,
                  snippet='SSR.initialData.end_time=' + str(initial.get('end_time')),
                  confidence=0.9, method='explicit_source_event_datetime')
    set_field(event, 'city', '苏州',
              snippet='SSR.initialData.city_name=' + str(city)
                      + '; province_name=' + str(province),
              confidence=0.9, method='explicit_source_city_alias_normalization')
    # The source's own city field is the only location claim made here; the page
    # carries no street address and no address is invented from it.
    set_field(event, 'location', city,
              snippet='SSR.initialData.city_name=' + str(city),
              confidence=0.7, method='explicit_source_city_field (not address enrichment)')

    venue_name = as_text(initial.get('venue_name'))
    if venue_name and not re.search(r'酒店预订|在线报名', venue_name):
        set_field(event, 'venue', venue_name,
                  snippet='SSR.initialData.venue_name=' + venue_name, confidence=0.9)
    else:
        found, snippet = venue_from(raw_description)
        if found:
            set_field(event, 'venue', found, snippet=snippet, confidence=0.85,
                      status='Needs Review', method='explicit_labelled_venue_in_source_description')
    organizer, snippet = organizer_from(initial, raw_description)
    if organizer:
        set_field(event, 'organizer', organizer, snippet=snippet, confidence=0.85,
                  status='Needs Review',
                  method='explicit_source_organizer_label'
                  if snippet.startswith('SSR.') else 'labelled_organizer_in_source_description')

    category, why = topic_category(initial.get('categorySlug'), as_text(initial.get('categoryName')))
    if category is None:
        category = name_category(name)
        why = 'event_name_keyword_rule'
    set_field(event, 'category', category,
              snippet=(why or 'unmapped_source_topic') + ' | categoryName='
                      + str(initial.get('categoryName')) + ' | event_name=' + name,
              confidence=0.6, status='Needs Review', method='source_topic_to_category_rule')
    return event


class HuodongjiaSource(PublicAccessSource):
    source_id = 'platform-huodongjia-suzhou'
    source_name = 'Huodongjia Suzhou'
    kind = 'event_platform'
    source_url = HOME_URL
    crawl_url = HOME_URL
    extractor = 'huodongjia_ssr'
    # Verified 2026-10-13: https://www.huodongjia.com/robots.txt returns HTTP 200 whose
    # body is the Next.js catch-all HTML page (0 user-agent/Disallow/Sitemap directives),
    # i.e. this host publishes NO robots policy for any path. That is "no usable rules",
    # not a denial, so the documented 404/410 semantics apply. The homepage and detail
    # pages are public and carry no access wall. Genuine denials (401/403, 5xx, redirects,
    # unexpected statuses) still stop the whole host.
    accept_soft_404_robots = True
    # The supplied city route is a JS-only shell; it is recorded but never requested.
    supplied_city_route = 'https://www.huodongjia.com/suzhou/'

    @staticmethod
    def is_public_url(url):
        parts = urlparse(url)
        return (public_https(url, HOST) and not parts.query
                and (parts.path in ('', '/') or DETAIL_PATH.fullmatch(parts.path) is not None))

    def collect(self):
        items = []
        self.investigation = {
            'scope': 'server-rendered homepage SSR discovery + Suzhou-only detail pages',
            'payload': '__NEXT_DATA__ props.pageProps.initialData',
            'supplied_city_route_requests': 0,
            'protected_api_requests': 0,
            'detail_pages_fetched': 0,
            'wrong_city_records_rejected': 0,
        }
        if urlparse(self.crawl_url).path not in ('', '/'):
            # The registry may still point at the JS-only shell. Collection stays on
            # the server-rendered homepage and the divergence is recorded, not followed.
            self.warnings.append(
                'Configured crawl URL ' + self.crawl_url + ' is not the server-rendered homepage; '
                'SSR discovery used ' + HOME_URL + ' instead'
            )
        try:
            home = self.public_page(HOME_URL)
        except Exception as exc:
            # Robots/access policy is a stop condition for the whole host.
            self.errors.append({'url': HOME_URL, 'error': str(exc)})
            return [*self.policy_items, *items]
        items.append(self.item(home, key='hdj-home', is_event=False, extractor='context'))
        if blocked_page(home.content):
            self.errors.append({'url': home.url, 'error': 'Access wall; no login/CAPTCHA/private API attempt'})
            return [*self.policy_items, *items]

        try:
            records = homepage_records(home.content)
        except ValueError as exc:
            records = []
            self.errors.append({'url': home.url, 'error': str(exc)})
        if not records:
            # Anchor discovery is a bounded fallback only; the payload is the source of truth.
            records = [{'event_uuid': uuid} for uuid in anchor_candidates(home.content)]
            if not records:
                if not any(home.url == error['url'] for error in self.errors):
                    self.errors.append({
                        'url': home.url,
                        'error': 'Homepage SSR payload yielded no event records and no event links; '
                                 'nothing is published from an unverified page state',
                    })
                return [*self.policy_items, *items]

        # Filter on the source's own city fields BEFORE any detail request is made.
        suzhou = [row for row in records
                  if is_suzhou(row.get('city_name'), row.get('province_name'))]
        self.investigation['wrong_city_records_rejected'] = len(records) - len(suzhou)
        if not suzhou:
            self.warnings.append(
                'Homepage SSR payload listed ' + str(len(records))
                + ' event records, none of them in Suzhou; no detail page was requested'
            )
            return [*self.policy_items, *items]

        for row in suzhou[:self.max_items]:
            url = candidate_detail_url(row.get('event_uuid'))
            if url is None:
                self.errors.append({'url': home.url, 'error': 'Invalid public event UUID in SSR payload; no request made'})
                continue
            try:
                detail = self.public_page(url)
            except Exception as exc:
                self.errors.append({'url': url, 'error': str(exc)})
                break  # Policy/access barrier: stop this host.
            items.append(self.item(detail, key='hdj-event-' + str(row.get('event_uuid')),
                                   extractor=self.extractor))
            self.investigation['detail_pages_fetched'] += 1
            if blocked_page(detail.content):
                self.errors.append({'url': detail.url, 'error': 'Detail access wall; no login/CAPTCHA/private API attempt'})
                break
        return [*self.policy_items, *items]
