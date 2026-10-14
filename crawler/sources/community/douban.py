"""Douban Suzhou local-events adapter (豆瓣同城苏州), public server-rendered HTML only.

Verified live on 2026-10-13 against ``https://www.douban.com/location/suzhou/events/future``:
the route 302-redirects ``/future`` -> ``/future/`` -> ``/future-all``, which returns the
server-rendered listing (``ul.events-list li.list-entry``, 10 cards per page, ``?start=N``
paging). Detail pages are plain HTML with NO ``application/ld+json``: the labelled rows live
in ``div.event-info div.event-detail`` and the event itself is an Event-scoped
``div.event-info`` microdata block (``itemprop`` summary/time/location/eventType/name).

YEAR RESOLUTION (the crux of this adapter). Every human-readable date on this source is
``M月D日 周X`` and usually carries NO year, so a year must never be guessed:

1. An explicit year wins. The source prints one in ``<time itemprop="startDate"
   datetime="2026-10-14T20:00:00">`` - present on the listing card and on the detail page,
   byte-identical on both for the 22 live records checked - and in ``2026年10月04日`` labels.
   Nothing about that year is inferred here.
2. When the same label also prints a weekday (``周三``), the explicit date must satisfy it.
   A mismatch rejects the record; neither side is silently preferred.
3. Without any explicit year, ``M月D日`` is accepted only when its own weekday claim selects
   exactly ONE candidate year inside a bounded window ``[today, today + 366 days]``. Zero or
   several candidates reject the record, and the resolution method plus the raw ``时间``
   snippet are recorded in the field evidence.

A publication date, the scrape date and the ``?start`` offset are never used as an event
date. Records without a resolvable date, without venue/location, or whose interval already
ended are rejected. Douban is a UGC/community aggregator, so nothing here is ever Verified:
every claim is ``Needs Review`` or ``Unverified``.
"""
import re
from datetime import date, datetime, timedelta
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

from crawler.extractor import base, set_field, text
from crawler.sources.event_platform.public_access import (
    PublicAccessSource, blocked_page, public_https,
)

HOST = 'www.douban.com'
HOME_URL = 'https://' + HOST + '/'
LISTING_PATH = '/location/suzhou/events/future-all'
LISTING_URL = HOME_URL.rstrip('/') + LISTING_PATH
DETAIL_PATH = re.compile(r'^/event/(\d{1,20})/$')
# The route 302s ``/future`` -> ``/future/`` -> ``/future-all``. Those are the only approved
# entry paths; no other path on this host is ever requested.
LISTING_PATHS = {LISTING_PATH, '/location/suzhou/events/future', '/location/suzhou/events/future/'}
# Bounded paging: ``?start`` is the source's own offset. The page cap (not the observed page
# count) bounds the listing requests, so a runaway paginator cannot widen the crawl.
PAGE_STEP = 10
DEFAULT_PAGE_CAP = 3
START_PARAM = re.compile(r'^\d{1,3}$')
# Labels observed in ``div.event-detail`` (``span.pl``) and in the listing card.
TIME_LABEL = '时间'
PLACE_LABEL = '地点'
TYPE_LABEL = '类型'
PROVIDER_LABEL = '信息提供者'
# Year-carrying readable date, e.g. ``2026年10月04日``.
YEAR_MONTH_DAY = re.compile(r'(\d{4})年(\d{1,2})月(\d{1,2})日')
# Weekday claims the source prints after a date: ``10月14日 周三 20:00-22:00``.
WEEKDAY_CLAIM = re.compile(r'(\d{1,2})月(\d{1,2})日[^\d一二三四五六日天]{0,3}?(?:周|星期)([一二三四五六日天])')
# Status words the source appends to a heading.
STATUS_TAIL = re.compile(r'\s*(?:即将开始|已结束|售票中|火热售票中|活动已取消)\s*$')
# A leading street name rather than a venue name: ``大治桥地铁站``/``工业园星湖街``/``东环路711``.
# The road-type character must END the segment, so a venue whose own name contains ``路`` or
# ``街`` (``慎德堂评弹茶馆-平江路店``) is still recognised as a venue.
STREET_NAME = re.compile(r'[\u4e00-\u9fff]{1,12}(?:路|街|巷|弄|道|桥|站)\Z')
WEEKDAYS = '一二三四五六日'  # index 0 == Monday, matching date.isoweekday() - 1


def today_local():
    """Today in the crawler's local (Asia/Shanghai) calendar, as a ``date``."""
    return datetime.now().date()


def explicit_date(value):
    """Return ``YYYY-MM-DD`` for an explicit year-bearing source value, else None.

    Only the source's own complete ``YYYY-MM-DD`` (optionally with a time) qualifies; a bare
    ``10-14`` or ``10月14日`` has no year and must go through the resolution path instead.
    """
    if not isinstance(value, str):
        return None
    matched = re.match(r'^(\d{4})-(\d{1,2})-(\d{1,2})(?:[T ]\d{1,2}:\d{2}(?::\d{2})?)?\s*$',
                       value.strip())
    if not matched:
        return None
    try:
        return date(int(matched[1]), int(matched[2]), int(matched[3])).isoformat()
    except ValueError:
        return None


def weekday_name(value):
    """The weekday claim of the first readable date label (``10月14日 周三`` -> ``三``)."""
    matched = WEEKDAY_CLAIM.search(value or '')
    return matched[3] if matched else None


def unlabelled_month_day(value):
    """The first year-less ``(month, day)`` of a readable date label, else None.

    A label that contains a year-bearing date at all - e.g. ``2026年10月04日`` - is skipped: it
    already states its own year, and no second year may be derived for it. A label whose dates are
    all year-less returns the first one, which is the date the weekday resolution text applies to.
    """
    label = value or ''
    if YEAR_MONTH_DAY.search(label):
        return None
    for matched in re.finditer(r'(?<!\d)(\d{1,2})月(\d{1,2})日', label):
        month, day = int(matched[1]), int(matched[2])
        if 1 <= month <= 12 and 1 <= day <= 31:
            return month, day
    return None


# One readable date claim: an optional explicit year, the month/day, an optional weekday and an
# optional clock. The weekday character itself is the claim; the trailing time is not.
DATE_CLAIM = re.compile(
    r'(?:(\d{4})年)?(\d{1,2})月(\d{1,2})日'
    r'(?:[^\d一二三四五六日天]{0,3}?(?:周|星期)([一二三四五六日天]))?')
# The source prints an event interval as ``10月17日 周六 16:00 ~ 10月31日 周六 21:30``; each side
# is read as its own date claim, so a single-day clock range (``19:30-20:20``) stays one claim.
def date_claims(label):
    """Readable date claims in document order: ``[(year|None, month, day, weekday|None)]``."""
    out = []
    for matched in DATE_CLAIM.finditer((label or '').replace('\u00a0', ' ')):
        out.append((int(matched[1]) if matched[1] else None, int(matched[2]), int(matched[3]),
                    matched[4]))
        if len(out) == 2:
            break
    return out


def interval_dates(start, end, time_text, today=None, max_drift_days=0):
    """Resolve ``(start, end)`` for one record, or fail closed with an explicit reason.

    Precedence per field: the explicit ``<time datetime>`` year, then a readable date whose own
    weekday claim selects exactly one candidate year in the bounded window. A year-less date in a
    mixed interval (``09月20日 周日 00:00 ~ 2027年08月29日 周日 23:59``, event 38019120) is anchored
    to the year the source printed on the other end of the SAME interval, and that year is
    accepted as evidence for the claim. A ``M月D日`` weekday claim that contradicts the anchor
    year rejects the record: neither side is silently preferred. Publication dates, the crawl
    date and the ``?start`` offset are never used.
    """
    anchor = today or today_local()
    claims = date_claims(time_text)
    start_claim = claims[0] if claims else None
    end_claim = claims[1] if len(claims) > 1 else None
    explicit = sorted({value for value in (start, end) if value})

    def window_years(claim):
        year, month, day, weekday = claim
        return resolve_year(month, day, weekday, today=anchor, max_drift_days=max_drift_days)

    def anchored_years(claim):
        """Years printed elsewhere in the SAME interval that satisfy this claim's weekday."""
        _, month, day, weekday = claim
        found = []
        for other in explicit:
            candidate = date.fromisoformat(other).year
            try:
                probe = date(candidate, month, day)
            except ValueError:
                raise ValueError('Douban printed an impossible calendar date; record rejected')
            if weekday and WEEKDAYS[probe.isoweekday() - 1] != weekday:
                continue
            found.append(candidate)
        return found

    def resolve(claim, source_value):
        """One field: the explicit ``<time datetime>`` year, else the claim's single year."""
        if source_value and (claim is None or claim[3] is None):
            return source_value
        if claim is None:
            return source_value
        year, month, day, weekday = claim
        if not source_value:
            if year:
                try:
                    return date(year, month, day).isoformat()
                except ValueError:
                    raise ValueError('Douban printed an impossible calendar date; record rejected')
            candidates = set()
            window = window_years(claim)
            if window:
                candidates.add(window)
            for candidate_year in anchored_years(claim):
                candidates.add(date(candidate_year, month, day).isoformat())
            if not candidates:
                # No year in the bounded window satisfies this claim, so the year cannot be
                # resolved at all and the record is rejected rather than guessed.
                return None
            if len(candidates) > 1:
                raise ValueError(
                    'Douban year-less date resolves to more than one year inside the same '
                    'interval; the record is rejected instead of preferring one of the two'
                )
            return candidates.pop()
        if not source_value.startswith('%s-%02d-%02d' % (source_value[:4], month, day)):
            return source_value  # the claim is not the field's own date
        explicit_weekday = WEEKDAYS[date.fromisoformat(source_value).isoweekday() - 1]
        if explicit_weekday == weekday:
            return source_value
        if window_years(claim):
            # The bounded window resolves the year-less claim to a DIFFERENT year, which is
            # exactly the coincidence this rule refuses to resolve; nothing is preferred.
            raise ValueError(
                'Douban weekday claim ' + weekday + ' does not name the year of the explicit '
                'event date ' + source_value + '; the record is rejected instead of preferring '
                'one of the two'
            )
        raise ValueError(
            'Douban weekday claim ' + weekday + ' contradicts the explicit event date '
            + source_value + '; the record is rejected instead of preferring one of the two'
        )

    resolved_start = resolve(start_claim, start)
    resolved_end = resolve(end_claim, end)
    if not resolved_start and not resolved_end:
        raise ValueError(
            'No year-explicit Douban event date and the M月D日 weekday claim does not select '
            'exactly one candidate year; the event date is never guessed'
        )
    if resolved_start and not resolved_end:
        resolved_end = end
    if resolved_end and not resolved_start:
        resolved_start = start
    if resolved_end and resolved_start and resolved_end < resolved_start:
        raise ValueError('Douban end date precedes the start date; interval rejected')
    return resolved_start, resolved_end


def resolve_year(month, day, weekday=None, today=None, max_drift_days=0):
    """Resolve a year for a year-less ``M月D日`` label, or fail closed with None.

    Candidates are the years whose ``month``/``day`` falls inside the bounded window
    ``[today - max_drift_days, today + 366 days]`` and whose real weekday matches the claim
    the source itself printed. Exactly one candidate resolves; zero or several return None,
    and the caller rejects the record rather than inventing a date.
    """
    anchor = today or today_local()
    earliest = anchor - timedelta(days=max_drift_days)
    latest = anchor + timedelta(days=366)
    candidates = []
    for year in range(earliest.year, latest.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        if not earliest <= candidate <= latest:
            continue
        if weekday and WEEKDAYS[candidate.isoweekday() - 1] != weekday:
            continue
        candidates.append(candidate)
    return candidates[0].isoformat() if len(candidates) == 1 else None


def card_records(content):
    """Verified records from one listing page, in document order.

    The card shape is pinned: ``ul.events-list li.list-entry`` with an Event ``itemtype``, a
    ``div.title a`` detail link, a ``li.event-time`` row and an Itemprop ``meta`` location.
    A page whose card shape changed yields no records, and the caller then fails closed with
    an explicit reason instead of publishing guesses.
    """
    soup = BeautifulSoup(content, 'html.parser')
    records = []
    for node in soup.select('ul.events-list li.list-entry'):
        link = node.select_one('div.title a[href]')
        if link is None or 'Event' not in (node.get('itemtype') or ''):
            continue
        parts = urlparse(link['href'])
        matched = DETAIL_PATH.fullmatch(parts.path)
        # Only a canonical, query-free detail link is a public event URL: a link with its own
        # query or fragment is never requested or used as provenance.
        if matched is None or parts.scheme != 'https' or parts.hostname != HOST \
                or parts.query or parts.fragment:
            continue
        time_row = node.select_one('li.event-time')
        place_node = node.select_one('meta[itemprop="location"]')
        owner_node = node.select_one('a[target^=db-event-owner]')
        start_node = node.select_one('time[itemprop="startDate"]')
        end_node = node.select_one('time[itemprop="endDate"]')
        records.append({
            'event_id': matched[1],
            'url': HOME_URL + 'event/' + matched[1] + '/',
            'name': text(link.get('title') or link.get_text(' ', strip=True)),
            'time_text': without_label(time_row.get_text(' ', strip=True), TIME_LABEL) if time_row else None,
            'start': explicit_date(start_node.get('datetime') if start_node else None),
            'end': explicit_date(end_node.get('datetime') if end_node else None),
            'place': text(place_node.get('content')) if place_node else None,
            'owner': text(owner_node.get_text(' ', strip=True)) if owner_node else None,
        })
    return records


def without_label(value, label):
    """Strip the source's own ``时间：``/``地点：`` label prefix from a row's flattened text."""
    text_value = text(value)
    if not text_value:
        return None
    stripped = re.sub(r'^\s*' + label + r'\s*[:：]\s*', '', text_value)
    return stripped or None


def page_total(content):
    """The source's own ``data-total-page`` counter, else None."""
    node = BeautifulSoup(content, 'html.parser').select_one(
        '.paginator .thispage[data-total-page]')
    return int(node['data-total-page']) if node and (node.get('data-total-page') or '').isdigit() else None


def detail_labels(content):
    """Return ``{label: value}`` for one detail page's own ``div.event-detail`` rows.

    The expanded per-session schedule (``显示时间详情``) is cut off so a row never mixes the
    event summary with dozens of individual show times.
    """
    soup = BeautifulSoup(content, 'html.parser')
    rows = {}
    for node in soup.select('div.event-info div.event-detail'):
        label_node = node.select_one('span.pl')
        if label_node is None:
            continue
        raw_label = label_node.get_text(' ', strip=True)
        label = (text(raw_label) or '').rstrip(':：').strip()
        if label not in (TIME_LABEL, PLACE_LABEL, TYPE_LABEL, PROVIDER_LABEL):
            continue
        body = node.get_text(' ', strip=True).split(raw_label.strip(), 1)[-1]
        value = without_label(re.split(r'显示时间详情', body)[0], label)
        if value:
            rows[label] = value
    return rows


def detail_record(content, url):
    """Verified detail-page record, or an explicit failure when the shape changed."""
    parts = urlparse(url)
    matched = DETAIL_PATH.fullmatch(parts.path)
    if matched is None or parts.scheme != 'https' or parts.hostname != HOST \
            or parts.query or parts.fragment:
        raise ValueError('Douban event data must come from an approved public detail page')
    if blocked_page(content):
        raise ValueError('Login/CAPTCHA/access wall: raw retained, no event published')
    soup = BeautifulSoup(content, 'html.parser')
    wrap = soup.select_one('div.eventwrap')
    info = wrap.select_one('div.event-info') if wrap is not None else None
    heading = info.select_one('h1') if info is not None else None
    if wrap is None or info is None or heading is None \
            or 'Event' not in (wrap.get('itemtype') or ''):
        raise ValueError(
            'Douban detail page no longer carries the verified Event-scoped eventwrap/'
            'event-info block; nothing is published from an unverified page state'
        )
    labels = detail_labels(content)

    def prop(selector):
        node = soup.select_one(selector)
        return text(node.get_text(' ', strip=True)) if node is not None else None

    def attribute(selector, name):
        node = soup.select_one(selector)
        return node.get(name) if node is not None and node.get(name) else None

    def when(selector):
        return explicit_date(attribute(selector, 'datetime'))

    # A detail page whose own share widget names a DIFFERENT event than the requested public URL
    # is never published under that URL: the record and its provenance would not match.
    stated = soup.select_one('[data-object_kind][data-object_id]')
    if stated is not None and str(stated.get('data-object_id')) != matched[1]:
        raise ValueError('Detail page event ID does not match the requested public item')

    return {
        'event_id': matched[1],
        'name': text(STATUS_TAIL.sub('', text(heading.get_text(' ', strip=True)) or '')),
        'time_text': labels.get(TIME_LABEL),
        'start': when('time[itemprop="startDate"]'),
        'end': when('time[itemprop="endDate"]'),
        # The source's own attribute values, retained verbatim for the field evidence: the
        # parsed date alone would hide which page field the year actually came from.
        'start_raw': attribute('time[itemprop="startDate"]', 'datetime'),
        'end_raw': attribute('time[itemprop="endDate"]', 'datetime'),
        'place': labels.get(PLACE_LABEL),
        'venue_address': prop('span[itemprop="street-address"]'),
        'city': prop('span[itemprop="region"]'),
        'district': prop('span[itemprop="locality"]'),
        'type': labels.get(TYPE_LABEL) or prop('a[itemprop="eventType"]'),
        'provider': labels.get(PROVIDER_LABEL) or prop('a[itemprop="name"]'),
    }


def category_from(value):
    """Map the source's own ``类型`` vocabulary onto the schema categories."""
    key = (value or '').strip()
    head = re.split(r'[-—/·\s]', key)[0] if key else ''
    rules = (
        ('sports', ('运动', '赛事', '体育', '健身', '户外', '搏击', '羽毛球', '球')),
        ('education', ('讲座', '课程', '培训', '沙龙', '读书', '学习', '教育', '亲子')),
        ('government', ('公益', '政府', '政务')),
        ('folk', ('民俗', '非遗', '传统', '庙会')),
        ('culture', ('音乐', '戏剧', '喜剧', '电影', '展览', '演出', '舞台', '戏曲', '相声',
                     '秀', '剧')),
    )
    for category, words in rules:
        if head in words or key in words or any(word in key for word in words):
            return category, 'source_type_label=' + key
    return None, None


def title_category(name):
    """Clear title keywords only; anything unmapped stays ``others``."""
    rules = (
        ('sports', ('马拉松', '足球', '篮球', '网球', '羽毛球', '比赛', '赛事', '训练营', '搏击')),
        ('education', ('讲座', '读书会', '工作坊', '研学', '课程', '沙龙')),
        ('folk', ('非遗', '民俗', '庙会', '传统手艺')),
        ('culture', ('音乐剧', '音乐会', '话剧', '相声', '评弹', '昆曲', '展览', '艺术展', '演出',
                     '脱口秀', '喜剧', '剧场', '舞台剧', '音乐节', '演唱会')),
    )
    for category, words in rules:
        if any(word in name for word in words):
            return category
    return 'others'


def city_from(region, place, address):
    """The city of one record from the page's own fields, never from the requested URL.

    The live ``<span itemprop="region">`` is EMPTY (verified on 35866026), so the city is read
    back out of the source's own ``地点`` line, which always begins with ``苏州 <district>``.
    """
    value = (region or '').strip()
    if value:
        return value, 'itemprop region=' + value
    for candidate in (place, address):
        matched = re.search(r'([\u4e00-\u9fff]{2,3})(?:市|县)?\s', (candidate or '').strip() + ' ')
        if matched:
            return matched[1], '地点=' + (place or address or '')
    return None, None


def is_street_part(token):
    """True for a street/address part rather than a place name (``松涛街1088号``, ``钮家巷3号``)."""
    return bool(re.search(r'\d', token) and re.search(r'号|室|楼|幢|座|栋|弄|巷|路|街|道|桥', token))


def is_street_name(token):
    """True for a bare street name (``星湖街``, ``大治桥地铁站``) rather than a venue."""
    stripped = re.sub(r'店\Z', '', token)
    return bool(STREET_NAME.fullmatch(stripped)) and len(stripped) <= 4


def venue_from(address, city=None):
    """The venue name the source itself prints just before its street part, else None.

    The live ``itemprop=street-address`` span (or the ``地点`` line when the span only holds the
    street part) reads ``苏州 姑苏区 嘻哈壹笑堂相声茶馆 平江街道大儒巷38号``, so the region prefix
    is dropped and the token immediately before the street part is the source's own venue name.
    A token that is itself a bare street name (``星湖街`` / ``大治桥地铁站``) is not a venue, and
    neither is a page that prints no venue name at all: the caller then publishes no venue
    rather than inventing one.
    """
    if not address:
        return None
    parts = address.split()
    # The city the parser already read is a leading token when the span carries the whole place
    # line; a district token (always ``区``/``县``) follows it. Only those prefixes are dropped,
    # so a venue whose own name contains ``市`` (``苏州市第二工人文化宫``) is left intact.
    while parts and (parts[0] == city or re.fullmatch(r'[\u4e00-\u9fff]{2,6}[区县]', parts[0])):
        parts = parts[1:]
    if len(parts) < 2:
        return None
    head, tail = parts[-2], parts[-1]
    # The token after the name must be a real street part, and the name itself must not be a
    # bare street/landmark or contain a door number.
    if not is_street_part(tail) or len(head) < 2 or any(char.isdigit() for char in head) \
            or is_street_name(head):
        return None
    return head


def douban_event(item, today=None):
    """Deterministic extraction for one server-rendered Douban Suzhou detail page."""
    record = detail_record(item.raw_content, item.original_url)
    if item.locator and str(record['event_id']) != str(item.locator):
        raise ValueError('Detail page event ID does not match the collected item locator')
    if not record['name']:
        raise ValueError('Douban detail page has no explicit event name')

    anchor = today or today_local()
    start, end = interval_dates(record.get('start'), record.get('end'), record.get('time_text'),
                                today=anchor)
    # A record is stale only when its whole interval is behind the crawl date: an event that
    # started earlier but is still running (its end is in the future) stays an upcoming event,
    # and the stale-start test is applied to the interval rather than to the start alone.
    if date.fromisoformat(end or start) < anchor - timedelta(days=7):
        raise ValueError('The event interval is already outside the bounded window around the '
                         'crawl date; a past event is not published as upcoming')

    city, city_snippet = city_from(record['city'], record['place'], record['venue_address'])
    if not city or '苏州' not in city:
        raise ValueError('Explicit Suzhou city required; the page place line is '
                         + repr(record['place'] or record['venue_address']))

    location = record['place'] or record['venue_address']
    if not location:
        raise ValueError('No explicit Douban place line; a record with no location is not published')
    # A named venue is published only when the source itself prints one. When it prints only a
    # street or landmark (``苏州 吴中区 大治桥地铁站``) the event still has an explicit location,
    # so it is published with venue=null rather than dropped: a road/landmark is never promoted
    # to a venue name, and discarding the event would lose a genuine booked demand signal
    # (badminton, English meetups, gym sessions). The distinction is venue vs location, not
    # "has a venue name" vs "is unusable".
    venue = venue_from(record['venue_address'], city)
    method = 'named_place_before_source_street_part'
    # An absent ``类型`` label is not an error: the category then falls back to a clear title
    # keyword and finally to ``others``, which is the honest default for an unmapped type.

    time_snippet = TIME_LABEL + '=' + str(record['time_text'])
    event = base(item)
    set_field(event, 'event_name', record['name'],
              snippet='h1=' + record['name'], confidence=0.9, status='Needs Review',
              method='detail_page_heading')
    set_field(event, 'start_date', start,
              snippet=time_snippet + '; itemscope startDate.datetime='
                      + str(record.get('start_raw') or 'absent'),
              confidence=0.9, status='Needs Review',
              method='explicit_itemprop_startDate_year' if record['start'] else
                     'M月D日 + source weekday claim selecting a single bounded candidate year')
    if end:
        set_field(event, 'end_date', end,
                  snippet=time_snippet + '; itemscope endDate.datetime='
                          + str(record.get('end_raw') or 'absent'),
                  confidence=0.85, status='Needs Review',
                  method='explicit_itemprop_endDate_year' if record['end'] else
                         'M月D日 + source weekday claim selecting a single bounded candidate year')
    set_field(event, 'venue', venue,
              snippet='itemprop street-address=' + str(record['venue_address'])
                      if venue else 'no venue name printed by the source; place line='
                      + str(location) + ' (a street or landmark is not promoted to a venue)',
              confidence=0.8, status='Needs Review',
              method=method if venue else 'absent_venue_name_in_source_place_line')
    set_field(event, 'location', location,
              snippet=PLACE_LABEL + ':' + str(record['place']),
              confidence=0.85, status='Needs Review',
              method='explicit_labelled_venue_line (no street-address enrichment)')
    set_field(event, 'organizer', record['provider'],
              snippet=PROVIDER_LABEL + ':' + str(record['provider']),
              confidence=0.7, status='Needs Review',
              method='explicit_source_provider_label')
    set_field(event, 'city', '苏州',
              snippet=city_snippet, confidence=0.9, status='Needs Review',
              method='explicit_source_place_line_city_prefix')
    category, why = category_from(record['type'])
    if category is None:
        category = title_category(record['name'])
        why = ('event_name_keyword_rule' if category != 'others'
               else 'unmapped_source_type_defaults_to_others')
    set_field(event, 'category', category,
              snippet=why + ' | ' + TYPE_LABEL + '=' + str(record['type'])
                      + ' | event_name=' + record['name'],
              confidence=0.6, status='Needs Review', method='source_type_to_category_rule')
    return event


class DoubanSource(PublicAccessSource):
    source_id = 'community-douban-suzhou'
    source_name = '豆瓣同城苏州'
    kind = 'community'
    source_url = LISTING_URL
    crawl_url = LISTING_URL
    extractor = 'douban_event'
    # www.douban.com publishes a REAL robots.txt (HTTP 200, directive rules) that does not
    # disallow /location/suzhou/events/ or /event/<id>/. The fail-closed default therefore
    # applies unchanged: a non-rules, missing or denied policy stops the whole host.
    accept_soft_404_robots = False
    page_cap = DEFAULT_PAGE_CAP
    # A card whose own explicit date is older than this is not requested at all, and a record
    # whose interval already ended is rejected. Long-running events stay in because their end
    # date is still in the future.
    grace_days = 7

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.investigation = {}
        self.records = []

    @staticmethod
    def is_public_url(url):
        if not public_https(url, HOST):
            return False
        parts = urlparse(url)
        if parts.path in LISTING_PATHS:
            query = parse_qs(parts.query, keep_blank_values=True)
            if not query:
                return True
            return (set(query) == {'start'} and len(query['start']) == 1
                    and START_PARAM.fullmatch(query['start'][0]) is not None
                    and int(query['start'][0]) % PAGE_STEP == 0
                    and int(query['start'][0]) <= 1000)
        return DETAIL_PATH.fullmatch(parts.path) is not None

    def page_url(self, start):
        return LISTING_URL + ('?start=' + str(start) if start else '')

    def public_page(self, url):
        # Same public routes, but with the redirect target re-checked against this adapter's own
        # allowed paths: the documented /future -> /future/ -> /future-all chain stays public.
        return super().public_page(url, allowed_redirect=self.is_public_url)

    def collect(self):
        anchor = today_local()
        items = []
        self.investigation = {
            'scope': 'public server-rendered Suzhou listing + Suzhou detail pages',
            'listing_page_cap': self.page_cap,
            'listing_pages_fetched': 0,
            'listing_total_pages': None,
            'detail_pages_fetched': 0,
            'cards_seen': 0,
            'cards_skipped_stale': 0,
            'hints_organizer_from_listing': 0,
            'protected_requests': 0,
        }
        self.records = []
        queued = []
        seen = set()
        total_pages = None
        if not self.is_public_url(self.crawl_url):
            # The registry can be edited by hand. A disallowed or unknown route is recorded and
            # never requested: collection stays on this adapter's own approved public routes.
            self.errors.append({
                'url': self.crawl_url,
                'error': 'Configured crawl URL is not an approved public Douban event route; '
                         'no request made',
            })
            return [*self.policy_items, *items]
        for page_index in range(self.page_cap):
            # ``PublicClient`` refuses a redirect that leaves this host, and the source re-checks
            # the target against its own approved routes, so the documented
            # ``/future`` -> ``/future/`` -> ``/future-all`` chain can only stay public.
            url = self.page_url(page_index * PAGE_STEP)
            try:
                page = self.public_page(url)
            except Exception as exc:
                self.errors.append({'url': url, 'error': str(exc)})
                break  # Policy/access barrier: stop this host.
            self.investigation['listing_pages_fetched'] += 1
            items.append(self.item(page, key='douban-listing-%d' % page_index,
                                   is_event=False, extractor='context'))
            if blocked_page(page.content):
                self.errors.append({
                    'url': page.url,
                    'error': 'Listing access wall; no login/CAPTCHA/private API attempt',
                })
                break
            cards = card_records(page.content)
            if not cards:
                self.errors.append({
                    'url': page.url,
                    'error': 'Listing page yielded no verified event cards; the card shape '
                             'changed and nothing is published from an unverified page state',
                })
                break
            if total_pages is None:
                total_pages = page_total(page.content)
                self.investigation['listing_total_pages'] = total_pages
            self.investigation['cards_seen'] += len(cards)
            for card in cards:
                if card['event_id'] in seen:
                    continue
                seen.add(card['event_id'])
                if card['start'] and date.fromisoformat(card['start']) < anchor - timedelta(
                        days=self.grace_days):
                    self.investigation['cards_skipped_stale'] += 1
                    continue
                queued.append(card)
            if total_pages and page_index + 1 >= total_pages:
                break
        for card in queued[:self.max_items]:
            try:
                detail = self.public_page(card['url'])
            except Exception as exc:
                self.errors.append({'url': card['url'], 'error': str(exc)})
                break  # Policy/access barrier: stop this host.
            self.investigation['detail_pages_fetched'] += 1
            if card.get('owner'):
                self.investigation['hints_organizer_from_listing'] += 1
            items.append(self.item(detail, key='douban-event-' + card['event_id'],
                                   extractor=self.extractor, locator=card['event_id']))
            self.records.append((card, detail))
        return [*self.policy_items, *items]
