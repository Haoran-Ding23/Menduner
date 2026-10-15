"""visitsz (苏州市旅游咨询中心 节庆日历) adapter over pure server-rendered pages.

Ground truth re-verified against the live public site on 2026-10-13:

* ``/robots.txt`` answers HTTP 404 (an HTML body, no rules), i.e. the host
  publishes no usable robots policy, so the documented 404/410 "no usable rules"
  semantics already apply. The strict default is kept: this source does NOT need
  the ``accept_soft_404_robots`` opt-in and leaves it ``False``.
* Listing: ``https://visitsz.wglj.suzhou.com.cn/festival-activity.aspx?page=N``
  (page 1 is the bare ``/festival-activity.aspx``). Server-rendered, no JS.
* Detail: ``https://visitsz.wglj.suzhou.com.cn/festival-detail.aspx?id=<16-digit>``.
  144 rows over pages 1-12 were all dated; no JavaScript, login or token is used.

Two verified hazards shape this adapter and are load-bearing:

1. **An invalid id is not an error page.** ``?id=9999999999999999`` answers
   HTTP 200 with the SAME template and EMPTY labels (``<h1></h1>``, ``来源：``,
   ``时间：``, ``地点：``). HTTP 200 is therefore never acceptance: a record is
   only published when the detail page carries a real explicit ``时间`` date AND
   a real ``地点`` value. ``来源`` is a publisher credit (a WeChat account) and is
   retained as provenance only - it is never turned into an organiser claim, and
   ``mp.weixin.qq.com`` is never requested (WeChat stays manual-only).
2. **The calendar is not ordered by event date.** Pages 1-12 of the live calendar
   held 92 not-yet-ended records interleaved with finished ones (page 5 carried
   only 2 of 12), so an individual past-dated page is never read as the end of the
   list. Re-measured 2026-10-15 over pages 1-35: 213 not-yet-ended records, thinning
   with depth, and page 45 carried none. Paging therefore stops on a run of
   future-free pages (``dry_page_limit``) instead of a guessed fixed depth, and the
   pager's advertised 662 pages are never followed. Only ``max_items`` bounds DETAIL
   requests.

Withdrawal conditions are explicit: a listing whose verified ``div.content-outer.list
ul`` block is gone, or whose rows no longer carry a parseable ``活动时间`` date, fails
closed with a reason instead of publishing anything. No value here is ever Verified.
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

HOST = 'visitsz.wglj.suzhou.com.cn'
BASE_URL = 'https://' + HOST
LISTING_PATH = '/festival-activity.aspx'
DETAIL_PATH = '/festival-detail.aspx'
DETAIL_QUERY = re.compile(r'^id=(\d{16})$')
# The site answers ?page=0 with HTTP 500 and ?page=abc with an empty body, so only
# real page numbers are treated as approved public routes.
LISTING_PAGE_QUERY = re.compile(r'^page=([1-9]\d{0,3})$')

# The portal is a Suzhou calendar; its own local day decides what has finished.
LOCAL_TIMEZONE = timezone(timedelta(hours=8))

# Verified listing skeleton (2026-10-13): one <li> per record under this block.
LIST_CONTAINER = 'div.content-outer.list ul'
LISTING_DATE = re.compile(
    r'活动时间\s*[：:]\s*(\d{4}-\d{2}-\d{2})(?:\s*-\s*(\d{4}-\d{2}-\d{2}))?')

# Verified detail skeleton: <div class="content-outer activity"><div class="info-panel">
# with <h1>, <article class="intro"> label rows and <article class="details">.
DETAIL_PANEL = 'div.content-outer.activity div.info-panel'
LABEL_ROW = re.compile(r'^(来源|时间|地点)\s*[：:]')
DETAIL_INTERVAL = re.compile(r'^(\d{4}-\d{2}-\d{2})(?:\s*-\s*(\d{4}-\d{2}-\d{2}))?$')

# "see the article"/"to be announced" style place values are not a location claim.
PLACEHOLDER_PLACE = re.compile(
    r'^(?:详见|见|参见|另见)[^，,。；;]{0,12}$'
    r'|^(?:待定|另行通知|以现场为准|以实际为准|暂无|无|TBD|待公布|未定)$',
    re.IGNORECASE)

# The title's leading 单位： prefix is the publisher/venue; the remainder is the event.
TITLE_PARTS = re.compile(r'^[^：:]{2,40}[：:]\s*(.+)$')
NAME_PREFIX = re.compile(r'^([^：:]{2,40})[：:]')

# Ordered, literal-keyword rules. First match wins; no match stays 'others'.
CATEGORY_RULES = (
    ('sports', re.compile(r'体育|足球|篮球|网球|马拉松|赛事|比赛|竞速|运动|田径|游泳|龙舟')),
    ('education', re.compile(r'讲座|研学|培训|公开课|沙龙|论坛|工作坊|课堂|读书会|分享会|夏令营|冬令营')),
    ('folk', re.compile(r'民俗|非遗|庙会|灯会|传统技艺|重阳|端午|中秋|春节|元宵|七夕|节气')),
    ('culture', re.compile(r'演出|音乐会|演唱会|舞剧|话剧|歌剧|戏曲|评弹|昆曲|相声|演奏|交响|合唱|'
                           r'音乐|剧场|剧院|放映|电影|展览|展映|美术|书法|篆刻|雕塑|摄影|艺术|'
                           r'博物馆|纪念馆|美术馆|阅读|书香|诗会|朗诵|市集|巡游|夜游')),
)

# Explicit organiser labels inside the body only; the 来源 credit is provenance.
# A value ends at the first space/punctuation/end, so a following sentence such as
# 演出简介 cannot be swept into an organiser name.
ORGANIZER_LABEL = re.compile(
    r'(?:主办单位|主办方|主办机构)\s*[：:]\s*([^，,。；;\n]{2,60}?)(?=[\s，,。；;]|$)')
ORGANIZER_SENTENCE = re.compile(r'由([^，,。；;\n]{2,60}?)(?:联合)?(?:主办|承办)')

# Body "时间" lines carry additional explicit dates; they are never the event date.
# A captured value ends at the next labelled row (地点/票价/...) - not at the first
# colon, because clock times such as 19:30 contain colons of their own.
BODY_TIME_LABEL = re.compile(
    r'(?:演出|活动|展览|展期|开放|举办|会期|放映|课程|讲座|比赛|赛事|报名)?时间\s*[：:]([^。\n]{0,200})')
BODY_VALUE_STOP = re.compile(
    r'(?:演出|活动|展览|展期|开放|举办|会期|放映|课程|讲座|比赛|赛事|报名|'
    r'票价|购票|地点|地址|方式|电话|咨询|简介|详情)\s*[：:]')
FULL_DATE_CN = re.compile(r'(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日')
FULL_DATE_ISO = re.compile(r'(20\d{2}-\d{2}-\d{2})')
WEIXIN_LINK = re.compile(r'https?://mp\.weixin\.qq\.com/[^\s"\'<>）)]+')


def local_today():
    """The calendar's own local day (Asia/Shanghai), used only to skip finished events."""
    return datetime.now(LOCAL_TIMEZONE).date()


def listing_url(page_number):
    """The public listing URL for one page; page 1 is the bare listing path."""
    return BASE_URL + LISTING_PATH + ('' if page_number == 1 else '?page=' + str(page_number))


def detail_page_id(url):
    """The 16-digit id of an approved public detail URL, else None."""
    if not public_https(url, HOST):
        return None
    parts = urlparse(url)
    if parts.path != DETAIL_PATH:
        return None
    matched = DETAIL_QUERY.fullmatch(parts.query or '')
    return matched[1] if matched else None


def iso_date(year, month, day):
    """``YYYY-MM-DD`` for a real calendar date, else None (no roll-over repair)."""
    try:
        return date(int(year), int(month), int(day)).isoformat()
    except ValueError:
        return None


def iso_interval(start_value, end_value=None):
    """``(start, end)`` ISO strings for an explicit interval, else None.

    ``end`` is None for a single-day record. An inverted interval is rejected
    rather than repaired.
    """
    start = iso_date(*str(start_value).split('-')) if start_value else None
    if not start:
        return None
    if not end_value:
        return start, None
    end = iso_date(*str(end_value).split('-'))
    if not end or end < start:
        return None
    return start, end


def listing_rows(content, page_url):
    """Calendar rows of one listing page, in page order.

    A page whose verified container is absent means the source changed shape and
    nothing may be published; a present-but-empty container is simply the end of
    the calendar and is reported as zero rows.
    """
    container = BeautifulSoup(content, 'html.parser').select_one(LIST_CONTAINER)
    if container is None:
        raise ValueError(
            'visitsz calendar listing no longer carries the verified '
            + LIST_CONTAINER + ' block; no event is published from an unverified page state')
    rows = []
    for node in container.select('li'):
        anchor = node.select_one('a[href]')
        if anchor is None or not text(anchor.get_text(' ', strip=True)):
            continue
        date_node = node.select_one('div.date')
        rows.append({
            'url': urljoin(page_url, anchor['href']),
            'title': text(anchor.get_text(' ', strip=True)),
            'date_text': (text(date_node.get_text(' ', strip=True)) if date_node else None),
        })
    return rows


def row_interval(date_text):
    """``(start, end, reason)`` for a listing row's 活动时间.

    ``reason`` is None when the row carries a real interval, otherwise the counter
    that explains why the row was dropped: 'undated_listing_rows_dropped' when the
    verified ``活动时间`` marker is absent, 'impossible_date_rows_dropped' for a date
    that is not a real calendar day, and 'inverted_interval_rows_dropped' for an end
    before its start (the live calendar holds one such row: 2026-09-30 - 2026-09-29).
    A bad interval is never repaired or guessed at.
    """
    matched = LISTING_DATE.search(date_text or '')
    if not matched:
        return None, None, 'undated_listing_rows_dropped'
    if iso_date(*matched[1].split('-')) is None:
        return None, None, 'impossible_date_rows_dropped'
    interval = iso_interval(matched[1], matched[2])
    if interval is None:
        return None, None, 'inverted_interval_rows_dropped'
    return interval[0], interval[1], None


def intro_fields(intro):
    """Label -> value map from the verified ``article.intro`` field block.

    The labels are what the source's editors write (来源/时间/地点); an empty label
    row keeps a None value, which is exactly how the invalid-id template answers.
    """
    fields = {}
    for node in intro.select('.entry'):
        raw = text(node.get_text(' ', strip=True))
        if not raw:
            continue
        matched = LABEL_ROW.match(raw)
        if matched:
            fields.setdefault(matched[1], text(raw[matched.end():]))
    return fields


def place_is_published(place):
    """False for an empty place or a "see the article" style placeholder."""
    if not place:
        return False
    return PLACEHOLDER_PLACE.fullmatch(place.strip('（）()【】 \u3000')) is None


def venue_from(name, place):
    """Venue name built only from literal page text, never a synthesised one.

    The title's own 单位 prefix is preferred when it also occurs in the published
    地点 (a cross-check between two independent page fields); otherwise the address
    tail after the last street number is taken verbatim from 地点. Both branches
    return the exact substring they came from.
    """
    matched = NAME_PREFIX.match(name)
    if matched:
        prefix = text(matched[1])
        if prefix and prefix in place:
            return prefix, 'title_organisation_prefix_also_present_in_source_place_field', 0.8
    index = place.rfind('号')
    if index >= 0:
        tail = text(place[index + 1:])
        if tail and 2 <= len(tail) <= 40 and not re.match(r'^[\d（(【]', tail):
            return tail, 'address_tail_after_last_street_number_in_source_place_field', 0.7
    return None, None, None


def category_from(name):
    """Category from the title's own keywords, else 'others'.

    The rules run over the event part of the title first (after the 单位 prefix)
    and only then over the whole title, so a venue name such as 戏曲百戏博物馆
    cannot outrank the event's own wording.
    """
    signals = []
    matched = TITLE_PARTS.match(name)
    if matched:
        signals.append(('event_name_part', text(matched[1])))
    signals.append(('title', name))
    for category, pattern in CATEGORY_RULES:
        for where, signal in signals:
            found = pattern.search(signal or '')
            if found:
                return category, 'keyword=' + found[0] + ' in ' + where
    return 'others', 'no_explicit_category_keyword_default_others'


def body_time_dates(details):
    """Complete dates the source itself writes in its own labelled body time lines.

    Only ``YYYY年M月D日`` and ``YYYY-MM-DD`` values qualify; bare 月日 values are never
    given an inferred year. Each value stops at the next labelled row, so a following
    地点/票价 row cannot contribute a date and a clock time's colons are irrelevant.
    """
    found = set()
    for matched in BODY_TIME_LABEL.finditer(details or ''):
        value = BODY_VALUE_STOP.split(matched[1])[0]
        for year, month, day in FULL_DATE_CN.findall(value):
            found.add(iso_date(year, month, day))
        for stamped in FULL_DATE_ISO.findall(value):
            found.add(iso_date(*stamped.split('-')))
    return {value for value in found if value}


def organizer_from(details):
    """Explicit organiser label in the body, else None; never the 来源 credit."""
    matched = ORGANIZER_LABEL.search(details or '')
    if not matched:
        matched = ORGANIZER_SENTENCE.search(details or '')
    if not matched:
        return None, None
    return text(matched[1]), matched[0]


def visitsz_event(item):
    """Deterministic extraction for one server-rendered visitsz detail page.

    Acceptance requires a non-empty h1, an explicit 时间 that parses as a real
    ``YYYY-MM-DD`` interval, and a non-placeholder 地点. Anything else raises, so
    the boilerplate/invalid-id template can never be published on its HTTP 200.
    """
    if blocked_page(item.raw_content):
        raise ValueError('Login/CAPTCHA/access wall: raw retained, no event published')
    requested = detail_page_id(item.original_url)
    if requested is None:
        raise ValueError('visitsz event data must come from an approved public detail URL')
    if item.locator and str(item.locator) != requested:
        raise ValueError('Detail page URL id does not match the collected item locator')

    soup = BeautifulSoup(item.raw_content, 'html.parser')
    panel = soup.select_one(DETAIL_PANEL)
    if panel is None:
        raise ValueError(
            'visitsz detail page no longer carries the verified ' + DETAIL_PANEL
            + ' block; no event is published from an unverified page state')
    heading = panel.select_one('header h1')
    intro = panel.select_one('header article.intro')
    if heading is None or intro is None:
        raise ValueError('visitsz detail page no longer carries the verified h1/来源-时间-地点 block')
    name = text(heading.get_text(' ', strip=True))
    if not name:
        raise ValueError(
            'visitsz detail page has no explicit event name; the invalid-id/boilerplate '
            'template is never published')

    fields = intro_fields(intro)
    if not fields:
        raise ValueError(
            'visitsz detail page no longer carries the verified 来源/时间/地点 label rows; '
            'nothing is published from an unverified page state')
    when = fields.get('时间')
    if not when:
        raise ValueError(
            'No explicit 时间 date on the visitsz detail page; undated records are '
            'rejected, not published')
    matched = DETAIL_INTERVAL.fullmatch(when)
    interval = iso_interval(*matched.groups()) if matched else None
    if interval is None:
        raise ValueError('visitsz 时间 value is not an explicit YYYY-MM-DD interval: ' + repr(when))
    start, finish = interval
    place = fields.get('地点')
    if not place_is_published(place):
        raise ValueError(
            'No explicit 地点 (venue/location) on the visitsz detail page: ' + repr(place)
            + '; placeholder and template values are never published')

    details_node = panel.select_one('article.details')
    details = text(details_node.get_text(' ', strip=True)) if details_node is not None else None

    event = base(item)
    set_field(event, 'event_name', name, snippet='h1=' + name, confidence=0.9)
    set_field(event, 'start_date', start, snippet='时间：' + when, confidence=0.9,
              method='explicit_labelled_detail_time (YYYY-MM-DD)')
    if finish:
        set_field(event, 'end_date', finish, snippet='时间：' + when, confidence=0.9,
                  method='explicit_labelled_detail_time (YYYY-MM-DD range)')
    set_field(event, 'location', place, snippet='地点：' + place, confidence=0.85,
              method='explicit_source_place_field (address as published, no enrichment)')

    venue, venue_method, venue_confidence = venue_from(name, place)
    if venue:
        set_field(event, 'venue', venue, snippet='地点：' + place, confidence=venue_confidence,
                  status='Needs Review', method=venue_method)

    # The source's own labelled 时间 is the published interval. When its body time
    # lines list other explicit dates, the interval stays as published but is
    # flagged with the alternatives instead of silently claiming to cover them.
    extra = sorted(value for value in body_time_dates(details)
                   if value < start or value > (finish or start))
    if extra:
        for field in ('start_date', 'end_date'):
            quality = event['field_evidence'].get(field)
            if quality and event.get(field):
                quality['status'] = 'Needs Review'
                quality['confidence'] = min(quality['confidence'], 0.6)
                quality['method'] += '; within_source_body_time_lines_list_other_dates'
        anchor = event['field_evidence']['start_date']
        anchor['snippet'] = ('时间：' + when + ' | body 时间 lines also list: ' + ', '.join(extra))
        anchor['candidates'] = sorted({start, *([finish] if finish else []), *extra})

    category, why = category_from(name)
    set_field(event, 'category', category, snippet=why + ' | title=' + name,
              confidence=0.6 if category != 'others' else 0.3, status='Needs Review',
              method='explicit_title_keyword_to_category_rule')

    organizer, organizer_snippet = organizer_from(details)
    # 来源 names the publishing WeChat account. It is provenance, never an organiser
    # name, and it is carried in the organiser claim's snippet (the value stays null)
    # so the credit and any original mp.weixin.qq.com link survive in the evidence
    # table. Those links are recorded, never requested - WeChat stays manual-only.
    credit = fields.get('来源')
    credit_parts = []
    if credit:
        credit_parts.append('来源：' + credit + ' (publisher credit, not an organiser claim)')
    links = WEIXIN_LINK.findall(item.raw_content)
    if links:
        credit_parts.append('原信息链接 ' + links[0] + ' (recorded as provenance, never requested)')
    provenance = ' | '.join(credit_parts) or None
    if organizer:
        set_field(event, 'organizer', organizer,
                  snippet=' | '.join(part for part in (organizer_snippet, provenance) if part),
                  confidence=0.75, status='Needs Review',
                  method='explicit_organiser_label_in_source_body')
    else:
        set_field(event, 'organizer', None, snippet=provenance, confidence=0.0,
                  method='source_credit_line_is_provenance_only; WeChat account is not an organiser')
    return event


class VisitszSource(PublicAccessSource):
    """Bounded public collection for the official Suzhou festival calendar."""

    source_id = 'tourism-visitsz-festival'
    source_name = '苏州市旅游咨询中心 节庆日历 (visitsz)'
    kind = 'tourism'
    source_url = BASE_URL + '/'
    crawl_url = BASE_URL + LISTING_PATH
    extractor = 'visitsz_detail'
    # Verified 2026-10-13: the host publishes no robots rules at all (HTTP 404), so the
    # documented 404/410 "no usable rules" semantics already apply. The strict default
    # is correct here and the soft-404 opt-in stays off.
    accept_soft_404_robots = False
    # The horizon is found adaptively, not fixed. Measured 2026-10-15 on the live
    # calendar: pages 1-12 carried 95 not-yet-ended records, but page 45 and beyond
    # carried none at all, because older pages are older postings about older events.
    # The yield is therefore front-loaded and becomes pure history with depth, so
    # paging continues while it is still paying and stops after a run of pages that
    # produced nothing future. page_cap remains the hard ceiling.
    page_cap = 40
    # Six consecutive future-free pages. Measured distribution: the deepest real
    # cluster of not-yet-ended records sits on page 35, and the first run of six
    # empty pages begins at 39, so this stops at 44 without cutting live material.
    dry_page_limit = 6
    investigation = {}

    def __init__(self, *args, page_cap=None, dry_page_limit=None, today=None, **kwargs):
        super().__init__(*args, **kwargs)
        if page_cap is not None:
            if page_cap < 1:
                raise ValueError('page_cap must be a positive number of listing pages')
            self.page_cap = page_cap
        if dry_page_limit is not None:
            if dry_page_limit < 1:
                raise ValueError('dry_page_limit must be a positive number of listing pages')
            self.dry_page_limit = dry_page_limit
        if today is not None:
            if not isinstance(today, date):
                raise ValueError('today must be a datetime.date')
            self.calendar_today = today
        else:
            self.calendar_today = local_today()

    @staticmethod
    def is_public_url(url):
        """Only the approved HTTPS listing and 16-digit detail routes are collectable."""
        if not public_https(url, HOST):
            return False
        parts = urlparse(url)
        if parts.path == LISTING_PATH:
            return parts.query == '' or LISTING_PAGE_QUERY.fullmatch(parts.query) is not None
        if parts.path == DETAIL_PATH:
            return DETAIL_QUERY.fullmatch(parts.query or '') is not None
        return False

    def collect(self):
        items = []
        self.investigation = {
            'scope': 'official Suzhou festival calendar: bounded listing pages -> dated detail pages',
            'paging': 'listing pages 1..page_cap, stopping after dry_page_limit pages with no future rows',
            'page_cap': self.page_cap,
            'dry_page_limit': self.dry_page_limit,
            'listing_pages_fetched': 0,
            'listing_rows_seen': 0,
            'undated_listing_rows_dropped': 0,
            'impossible_date_rows_dropped': 0,
            'inverted_interval_rows_dropped': 0,
            'past_dated_listing_rows_dropped': 0,
            'offhost_or_invalid_row_links_dropped': 0,
            'candidate_detail_urls': 0,
            'detail_pages_fetched': 0,
            'protected_api_requests': 0,
            'wechat_requests': 0,
            'stopped_reason': None,
        }
        page = None
        candidates = []
        seen_ids = set()
        dry_streak = 0
        for page_number in range(1, self.page_cap + 1):
            url = listing_url(page_number)
            try:
                page = self.public_page(url)
            except PermissionError as exc:
                # Host-level policy barrier: stop this host and keep what was verified.
                self.errors.append({'url': url, 'error': str(exc)})
                break
            except Exception as exc:
                self.errors.append({'url': url, 'error': str(exc)})
                if page_number == 1:
                    return [*self.policy_items, *items]
                break
            items.append(self.item(page, key='visitsz-listing-%d' % page_number,
                                   is_event=False, extractor='context'))
            self.investigation['listing_pages_fetched'] += 1
            if blocked_page(page.content):
                self.errors.append({'url': page.url,
                                    'error': 'Access wall; no login/CAPTCHA/private API attempt'})
                break
            try:
                rows = listing_rows(page.content, page.url)
            except ValueError as exc:
                self.errors.append({'url': page.url, 'error': str(exc)})
                break
            if not rows:
                if page_number == 1:
                    self.warnings.append(
                        'visitsz calendar listing page 1 carries no entries; nothing published')
                break  # End of the calendar, not a failure.
            self.investigation['listing_rows_seen'] += len(rows)
            time_markers = 0
            future_on_page = 0
            for row in rows:
                start, finish, dropped = row_interval(row['date_text'])
                if dropped is not None:
                    self.investigation[dropped] += 1
                    if dropped == 'undated_listing_rows_dropped':
                        continue
                    # A 活动时间 marker exists but its interval cannot be real: the row
                    # is dropped, never repaired, and it still counts as a marker so a
                    # single bad row cannot be mistaken for a changed listing shape.
                    time_markers += 1
                    continue
                time_markers += 1
                if (finish or start) < self.calendar_today.isoformat():
                    self.investigation['past_dated_listing_rows_dropped'] += 1
                    continue
                future_on_page += 1
                row_id = detail_page_id(row['url'])
                if row_id is None:
                    self.investigation['offhost_or_invalid_row_links_dropped'] += 1
                    continue
                if row_id in seen_ids:
                    continue
                seen_ids.add(row_id)
                candidates.append({'id': row_id, 'url': row['url']})
            if time_markers == 0:
                self.errors.append({
                    'url': page.url,
                    'error': 'visitsz listing rows no longer carry a parseable 活动时间 date; '
                             'the listing shape changed and nothing is published from it',
                })
                break
            # Older pages are older postings about older events, so the not-yet-ended
            # yield falls off with depth. A run of future-free pages means the calendar
            # has been read past its useful horizon; continuing would spend listing
            # requests on history only.
            if future_on_page:
                dry_streak = 0
            else:
                dry_streak += 1
                if dry_streak >= self.dry_page_limit:
                    self.investigation['stopped_reason'] = (
                        'dry_horizon: %d consecutive listing pages carried no not-yet-ended row'
                        % dry_streak)
                    break

        self.investigation['candidate_detail_urls'] = len(candidates)
        for row in candidates[:self.max_items]:
            try:
                detail = self.public_page(row['url'])
            except PermissionError as exc:
                self.errors.append({'url': row['url'], 'error': str(exc)})
                break  # Host-level policy barrier: stop this host.
            except Exception as exc:
                # One stale/unsupported id must not discard the verified rest.
                self.errors.append({'url': row['url'], 'error': str(exc)})
                continue
            items.append(self.item(detail, key='visitsz-detail-' + row['id'],
                                   extractor=self.extractor, locator=row['id']))
            self.investigation['detail_pages_fetched'] += 1
            if blocked_page(detail.content):
                self.errors.append({'url': detail.url,
                                    'error': 'Detail access wall; no login/CAPTCHA/private API attempt'})
                break
        return [*self.policy_items, *items]
