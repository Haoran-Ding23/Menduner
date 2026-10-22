"""好展会信息网 (haozhanhui.com) — Suzhou exhibition schedule, server-rendered HTML only.

Why this source exists
----------------------
Exhibition demand was covered by `cnena` (one venue's schedule, over plain HTTP with a
hostname-mismatched certificate) and by the Expo Centre's own JSON calendar. Both describe a
single venue. This host publishes the city's whole year of exhibition records in one served
page, with a date on every row, so it closes a real coverage gap rather than adding a mirror.

Verified live on 2026-10-15, with TLS verification on, no credential, and robots.txt absent
(HTTP 404 = no rules):

  * listing ``https://www.haozhanhui.com/zhanlanjihua/2026__suzhou__c_1.html`` -> 200 text/html,
    73-92 KB, title ``2026年苏州展会信息_2026年苏州展览计划``. Its ``<li>`` rows carry the source's
    own three fields as ``YYYY-MM-DD 【行业】 <a href="/exh/exh_index_XXXXXX.html">展会名</a>``.
    222 rows were parsed; the page is the whole city's plan and is NOT ordered by date, which is
    why paging/scanning is by direction rather than by "the first past row".
  * a row's date is the exhibition's START day. The detail page states the full interval next to
    the venue block, e.g. ``2027-04-15~04-17`` with ``展会场馆：苏州国际博览中心`` and
    ``组织单位：上海有色网信息科技股份有限公司``; the end day carries no year and belongs to the
    start day's year, which the extractor only accepts when the result is a real, non-inverted
    calendar interval.
  * detail route shape: ``/exh/exh_index_<6 lowercase letters>.html``; venue pages
    (``/place/<id>.html``) and organiser pages (``/org/<id>.html``) are other routes and are
    deliberately NOT collected.

Nothing about the site is assumed: a listing whose verified row shape is gone fails closed, a
detail whose interval or venue block is gone rejects that record, and a record whose own venue
is not explicitly in Suzhou is rejected rather than published as local demand. The list date is
never used as evidence — the published interval with the labelled venue is.
"""
import re
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from crawler.extractor import base, set_field, text
from crawler.sources.event_platform.public_access import (
    PublicAccessSource,
    blocked_page,
    public_https,
)

HOST = 'www.haozhanhui.com'
BASE_URL = 'https://' + HOST
# The city plan route its own navigation links use; the year is part of the source's URL.
LISTING_PATH = '/zhanlanjihua/2026__suzhou__c_1.html'
DETAIL_PATH = re.compile(r'^/exh/exh_index_[a-z0-9]{6}\.html$')
# A row is exactly: date, bracketed industry, then the exhibition's own link and title.
ROW = re.compile(r'^(20\d{2}-\d{2}-\d{2})\s*【([^】]{1,24})】\s*(.+)$')
# The published interval sits immediately above the venue block in div.exhinfotop.
INTERVAL = re.compile(r'(20\d{2})-(\d{2})-(\d{2})~(\d{2})-(\d{2})')
VENUE_LABEL = '展会场馆'
ORGANIZER_LABEL = '组织单位'

LOCAL_TIMEZONE = timezone(timedelta(hours=8))

# Ordered keyword rules over the source's own 行业 label and the title; no match stays 'others'.
INDUSTRY_CATEGORY = {
    '工业机械': 'business', '电子电力': 'business', '能源矿产': 'business',
    '化工环保': 'business', '建筑建材': 'business', '交通运输': 'business',
    '信息通信': 'business', '金融保险': 'business', '农林业': 'business',
    '食品饮料': 'business', '纺织服装': 'business', '包装印刷': 'business',
    '汽车配件': 'business', '冶金矿产': 'business', '办公文教': 'business',
    '旅游酒店': 'business', '商业贸易': 'business', '综合其他': 'business',
    '医疗器械': 'business', '药品保健': 'business', '运动休闲': 'sports',
    '文化艺术': 'culture', '教育': 'education',
}
CULTURE_TITLE = re.compile(r'艺术|文化|美术|书|动漫|文创|非遗|音乐')
SPORTS_TITLE = re.compile(r'体育|运动|健身|马拉松|球')
EDUCATION_TITLE = re.compile(r'教育|培训|学术|论坛|研讨|峰会|会议')


def local_today():
    """The calendar's own local day (Asia/Shanghai), used only to skip finished exhibitions."""
    return datetime.now(LOCAL_TIMEZONE).date()


def listing_rows(content, page_url=BASE_URL + LISTING_PATH):
    """``[{date, industry, title, url}]`` in page order, or raise when the shape changed.

    The href the page publishes is relative, so it is resolved against the page it was served
    from — a row is only ever a candidate on this host. A page that no longer carries any
    verified row means the source changed shape and nothing may be published from it; a
    present-but-empty result is the caller's business.
    """
    soup = BeautifulSoup(content, 'html.parser')
    rows = []
    for node in soup.find_all('li'):
        label = text(node.get_text(' ', strip=True))
        matched = ROW.match(label) if label else None
        anchor = node.find('a', href=True)
        if not matched or anchor is None or not isinstance(anchor['href'], str):
            continue
        rows.append({
            'date': matched[1],
            'industry': matched[2],
            'title': text(anchor.get_text(' ', strip=True)) or text(matched[3]),
            'url': urljoin(page_url, anchor['href']),
        })
    return rows


def detail_record(content):
    """``(start, end, venue, organizer, name)`` from one verified detail page, else raises.

    Every value comes from the page's own labelled block: the interval printed next to the venue,
    the 展会场馆 link text, the 组织单位 link text and the ``div.exhname h1`` heading. The h1 also
    carries the host's own status badges in a ``div.exhjianyi`` child (建议参加 / 好展会认证展会),
    which are removed rather than published as part of the exhibition's name; the page's ``<title>``
    prints the name on its own inside 【】 and is used to cross-check the result.
    """
    soup = BeautifulSoup(content, 'html.parser')
    heading = soup.select_one('div.exhname h1')
    if heading is None:
        raise ValueError('haozhanhui detail page carries no div.exhname h1 exhibition name')
    for badge in heading.select('div.exhjianyi, span'):
        badge.decompose()
    name = text(heading.get_text(' ', strip=True))
    if not name:
        raise ValueError('haozhanhui detail page carries no exhibition name in div.exhname h1')
    title = text(soup.title.get_text(strip=True)) if soup.title is not None else None
    if not title or name not in title:
        raise ValueError(
            'haozhanhui detail <title> does not carry the heading this page is about; the page '
            'shape changed and nothing is published from it (title=' + str(title)[:80] + ')')

    block = soup.select_one('div.exhinfotop')
    if block is None:
        raise ValueError('haozhanhui detail page carries no div.exhinfotop information block')
    interval = INTERVAL.search(text(block.get_text(' ', strip=True)) or '')
    if not interval:
        raise ValueError('haozhanhui detail page carries no explicit YYYY-MM-DD~MM-DD interval')
    start = iso_date(interval[1], interval[2], interval[3])
    # The end day is printed without its year; it belongs to the start day's year. A shorter end
    # day is not repaired by rolling the year over: the interval is rejected instead.
    end = iso_date(interval[1], interval[4], interval[5])
    if not start or not end or end < start:
        raise ValueError('haozhanhui interval is not a real calendar interval: ' + interval[0])

    venue = labelled_value(block, VENUE_LABEL)
    if not venue:
        raise ValueError('haozhanhui detail page carries no 展会场馆 venue')
    if '苏州' not in venue:
        raise ValueError('The exhibition venue is not explicitly in Suzhou: ' + venue)
    return start, end, venue, labelled_value(block, ORGANIZER_LABEL), name


def labelled_value(block, label):
    """The text of the ``<li>`` whose ``<strong>`` label matches, else None."""
    for node in block.select('li'):
        strong = node.select_one('strong')
        if strong is None or label not in text(strong.get_text(' ', strip=True)):
            continue
        for child in node.find_all(['a', 'span']):
            value = text(child.get_text(' ', strip=True))
            if value:
                return value
        remainder = text(node.get_text(' ', strip=True)).replace(label, '', 1).strip('：: ')
        return remainder or None
    return None


def iso_date(year, month, day):
    """``YYYY-MM-DD`` for a real calendar date, else None (never repaired)."""
    try:
        return date(int(year), int(month), int(day)).isoformat()
    except ValueError:
        return None


def normalize_name(value):
    """A title without its bracket style, so 【x】 and （x） are the same name."""
    return re.sub(r'[【】（）()\[\]〔〕]', '', value or '').strip()


def category_of(industry, name):
    """Category from the source's own 行业 label, then a literal title keyword, else 'others'."""
    mapped = INDUSTRY_CATEGORY.get(industry or '')
    if mapped:
        return mapped, 'industry=' + industry
    for category, pattern in (('culture', CULTURE_TITLE), ('sports', SPORTS_TITLE),
                              ('education', EDUCATION_TITLE)):
        found = pattern.search(name or '')
        if found:
            return category, 'title keyword=' + found[0]
    return 'others', 'no_explicit_category_keyword_default_others'


# The 行业 label is a listing-row field that has no home in the unified event schema. It is not
# invented onto the item: the collector records it against the item key it is about to publish,
# and the extractor reads its own row back through that key.
industry_by_key = {}


def haozhanhui_exhibition(item):
    """Deterministic extraction for one collected 好展会 detail page."""
    if blocked_page(item.raw_content):
        raise ValueError('Login/CAPTCHA/access wall: raw retained, no event published')
    start, end, venue, organizer, name = detail_record(item.raw_content)
    # The listing row's own title is the item key `collect` assigned. It is compared without
    # bracket style, because the same name is printed with 【】 on one page and （） on the other.
    if item.locator and normalize_name(item.locator) != normalize_name(name):
        raise ValueError('haozhanhui detail heading does not match the collected listing row: '
                         + name + ' vs ' + str(item.locator))

    event = base(item)
    set_field(event, 'event_name', name,
              snippet='div.exhname h1=' + name, confidence=0.9,
              method='detail_page_heading')
    set_field(event, 'start_date', start,
              snippet='exhinfotop interval=' + start + '~' + end, confidence=0.85,
              method='explicit_published_interval_start')
    set_field(event, 'end_date', end,
              snippet='exhinfotop interval=' + start + '~' + end, confidence=0.8,
              method='explicit_published_interval_end (year from the interval start)')
    set_field(event, 'venue', venue, snippet=VENUE_LABEL + '：' + venue, confidence=0.85,
              method='explicit_labelled_venue_field')
    # The venue field is the published exhibition hall, not a street address, so the location
    # claim carries the same value the source prints instead of an enriched address.
    set_field(event, 'location', venue, snippet=VENUE_LABEL + '：' + venue, confidence=0.8,
              method='explicit_labelled_venue_field (not address enrichment)')
    set_field(event, 'organizer', organizer,
              snippet=ORGANIZER_LABEL + '：' + str(organizer) if organizer else None,
              confidence=0.75 if organizer else 0.0,
              method='explicit_labelled_organizer_field' if organizer
                     else 'no organiser label published')
    category, why = category_of(industry_by_key.get(item.item_key), name)
    set_field(event, 'category', category, snippet=why + ' | title=' + name,
              confidence=0.6 if category != 'others' else 0.3, status='Needs Review',
              method='source_industry_label_then_title_keyword_rule')
    return event


class HaozhanhuiSource(PublicAccessSource):
    """Bounded public collection for the server-rendered Suzhou exhibition plan."""

    source_id = 'platform-haozhanhui-suzhou'
    source_name = '好展会信息网 苏州展会计划 (haozhanhui)'
    kind = 'event_platform'
    source_url = BASE_URL + '/suzhou/'
    crawl_url = BASE_URL + LISTING_PATH
    extractor = 'haozhanhui_exhibition'
    # Verified 2026-10-15: the host publishes no robots.txt at all (HTTP 404), so the documented
    # 404/410 "no usable rules" semantics apply and the strict default stays correct.
    accept_soft_404_robots = False
    # The city page carries the whole year in one document; the furthest window is deliberately
    # bounded on the run day so a record whose start has passed is not republished as upcoming.
    grace_days = 0
    investigation = {}

    def __init__(self, *args, today=None, **kwargs):
        super().__init__(*args, **kwargs)
        if today is not None and not isinstance(today, date):
            raise ValueError('today must be a datetime.date')
        self.calendar_today = today or local_today()
        industry_by_key.clear()

    @staticmethod
    def is_public_url(url):
        """Only the approved HTTPS city plan and its own detail routes are collectable."""
        if not public_https(url, HOST):
            return False
        parts = urlparse(url)
        if parts.path == LISTING_PATH:
            return parts.query == '' and parts.fragment == ''
        return DETAIL_PATH.fullmatch(parts.path) is not None and not parts.query

    def collect(self):
        items = []
        self.investigation = {
            'scope': 'public server-rendered Suzhou exhibition plan -> dated detail pages',
            'listing_rows_seen': 0,
            'rows_undated_dropped': 0,
            'rows_outside_suzhou_route_dropped': 0,
            'past_dated_rows_dropped': 0,
            'candidate_detail_urls': 0,
            'detail_pages_fetched': 0,
            'records_rejected': 0,
        }
        if not self.is_public_url(self.crawl_url):
            self.errors.append({
                'url': self.crawl_url,
                'error': 'Configured crawl URL is not the approved public Suzhou plan route; '
                         'no request made',
            })
            return [*self.policy_items, *items]
        try:
            listing = self.public_page(self.crawl_url)
        except Exception as exc:
            self.errors.append({'url': self.crawl_url, 'error': str(exc)})
            return [*self.policy_items, *items]
        items.append(self.item(listing, key='haozhanhui-listing', is_event=False,
                               extractor='context'))
        if blocked_page(listing.content):
            self.errors.append({'url': listing.url,
                                'error': 'Access wall; no login/CAPTCHA attempt'})
            return [*self.policy_items, *items]
        rows = listing_rows(listing.content, listing.url)
        if not rows:
            self.errors.append({
                'url': listing.url,
                'error': 'The verified row shape (date 【industry】 link) is gone; nothing is '
                         'published from an unverified page state',
            })
            return [*self.policy_items, *items]

        candidates = []
        seen = set()
        for row in rows:
            self.investigation['listing_rows_seen'] += 1
            if not iso_date(*row['date'].split('-')):
                self.investigation['rows_undated_dropped'] += 1
                continue
            if not self.is_public_url(row['url']):
                # Venue/organiser pages and off-host links are other routes: never requested.
                self.investigation['rows_outside_suzhou_route_dropped'] += 1
                continue
            if row['date'] < (self.calendar_today - timedelta(days=self.grace_days)).isoformat():
                # The page is not ordered by date and reaches back years; a finished exhibition
                # is never republished as upcoming demand.
                self.investigation['past_dated_rows_dropped'] += 1
                continue
            if row['url'] in seen:
                continue
            seen.add(row['url'])
            candidates.append(row)
        candidates.sort(key=lambda row: row['date'])
        self.investigation['candidate_detail_urls'] = len(candidates)

        for row in candidates[:self.max_items]:
            try:
                detail = self.public_page(row['url'])
            except Exception as exc:
                # One stale or unsupported detail must not discard the verified rest.
                self.errors.append({'url': row['url'], 'error': str(exc)})
                continue
            self.investigation['detail_pages_fetched'] += 1
            if blocked_page(detail.content):
                # The walled page is retained verbatim as the observed evidence, and its record is
                # refused with an explicit reason instead of being handed to extraction as if it
                # were a page about an exhibition.
                self.errors.append({
                    'url': detail.url,
                    'error': 'Detail access wall; no login/CAPTCHA/private API attempt',
                })
                continue
            code = row['url'].rsplit('/', 1)[-1].removesuffix('.html').rsplit('_', 1)[-1]
            item = self.item(detail, key='haozhanhui-' + code, extractor=self.extractor,
                             locator=row['title'])
            industry_by_key[item.item_key] = row['industry']
            items.append(item)
        return [*self.policy_items, *items]
