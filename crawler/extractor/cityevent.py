"""Source-specific event extraction; uncertain dates never become invented dates."""
import re
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from crawler.extractor import base, text, set_field, label_organizer

EVENT_WORDS = re.compile(r'音乐会|演唱会|艺术周|文化节|展览|特展|文博会|博览会|讲座|嘉年华|盛典|足球|比赛|赛事')


def category(name):
    if re.search(r'足球|比赛|赛事|电竞|村镇赛', name):
        return 'sports'
    if re.search(r'讲座|研学|培训', name):
        return 'education'
    if re.search(r'博览会|会议|展销', name):
        return 'business'
    return 'culture'


def article(item):
    soup = BeautifulSoup(item.raw_content, 'html.parser')
    host = urlparse(item.original_url).hostname
    if host == 'www.sipac.gov.cn':
        body = soup.select_one('#zoomcon')
        title = soup.select_one('h1')
    elif host == 'wglj.suzhou.gov.cn':
        body = soup.select_one('.con_details .text')
        title = soup.select_one('.con_details h2')
    elif host == 'www.subaonet.com':
        body = soup.select_one('#arcBodyText')
        title = soup.select_one('.msg-title .title-text')
    else:
        raise ValueError('Unsupported official/media article host')
    if body is None or title is None:
        raise ValueError('Supported article body/title selectors missing; no event invented')
    heading = text(title.get_text(' ', strip=True))
    paragraphs = [text(n.get_text(' ', strip=True)) for n in body.select('p') if n.get_text(strip=True)]
    if not paragraphs:
        raise ValueError('No textual event announcement in article')
    lead = paragraphs[0]
    # Only the explicit leading event date. Later historical/biographical dates,
    # publication metadata, footer dates and relative "yesterday" are excluded.
    date_match = re.match(r'^(?:(20\d{2})年)?(\d{1,2})月(\d{1,2})日', lead)
    if not date_match:
        raise ValueError('No explicit leading event date; publication/relative dates are not substituted')
    if '取消' in heading or re.search(r'已取消|活动取消|演出取消|赛事取消', lead):
        raise ValueError('Cancelled event: raw retained, not published')
    main = lead[date_match.end():].lstrip('，, ')
    occurrence = re.search(r'^(.{3,180}?)在([^。]{2,70}?)(?:举办|举行|启幕|开幕|上演)', main)
    event_name = text(occurrence[1]) if occurrence else heading
    if not EVENT_WORDS.search(event_name):
        raise ValueError('No supported single named event in announcement')
    years = set(re.findall(r'(?<!\d)(20\d{2})(?!\d|杯)', event_name))
    if date_match[1]:
        year = date_match[1]
    elif len(years) == 1:
        year = next(iter(years))
    else:
        raise ValueError('Event year is not explicit; article publication year is not substituted')
    event = base(item)
    set_field(event, 'event_name', event_name, snippet=lead if occurrence else heading,
              confidence=0.8, status='Unverified' if occurrence else 'Needs Review',
              method='explicit_named_event_in_article' if occurrence else 'article_headline_to_event_name')
    inferred = not date_match[1]
    set_field(event, 'start_date', f'{year}-{int(date_match[2]):02}-{int(date_match[3]):02}',
              snippet=lead, confidence=0.75 if inferred else 0.9,
              status='Needs Review' if inferred else 'Unverified',
              method='leading_body_month_day + explicit_event_year' if inferred else 'explicit_leading_event_date')
    finish = re.search(r'(?:持续|展期|活动将持续)至\s*(?:(20\d{2})年)?(\d{1,2})月(\d{1,2})日', lead)
    if finish:
        set_field(event, 'end_date', f'{finish[1] or year}-{int(finish[2]):02}-{int(finish[3]):02}',
                  snippet=finish[0], confidence=0.75, status='Needs Review',
                  method='explicit_event_end_month_day + explicit_event_year')
    if occurrence:
        place = text(occurrence[2])
        set_field(event, 'venue', place, snippet=occurrence[0], confidence=0.8)
        set_field(event, 'location', place, snippet=occurrence[0], confidence=0.8,
                  method='explicit_event_place_phrase (not address enrichment)')
    set_field(event, 'category', category(event_name), snippet=event_name, confidence=0.6,
              status='Needs Review', method='event_category_rule')
    organizer = label_organizer(body.get_text('\n', strip=True))
    set_field(event, 'organizer', organizer, confidence=0.8)
    return event


def olympic(item):
    soup = BeautifulSoup(item.raw_content, 'html.parser')
    details = soup.select_one('.hdxx_ncen')
    if details is None:
        raise ValueError('Official activity detail labels missing')
    heading = details.find_previous('h2')
    if heading is None:
        raise ValueError('Official event heading missing')
    name = text(heading.get_text(' ', strip=True))
    if not name:
        raise ValueError('Official event name missing')
    fields = {}
    for row in details.select('span'):
        value = row.select_one('font')
        if value:
            label = text(row.get_text(' ', strip=True).split(value.get_text(' ', strip=True), 1)[0])
            fields[label] = text(value.get_text(' ', strip=True))
    dates = fields.get('活动日期') or ''
    matched = re.fullmatch(r'(20\d{2}-\d{1,2}-\d{1,2})(?:\s*-\s*(20\d{2}-\d{1,2}-\d{1,2}))?', dates)
    if not matched:
        raise ValueError('Explicit complete activity date missing/ambiguous')
    place = fields.get('活动地点')
    if not place or '苏州' not in place:
        raise ValueError('Explicit Suzhou activity location missing')
    if re.search(r'已取消|活动取消|赛事取消', name + details.get_text()):
        raise ValueError('Cancelled event: raw retained, not published')
    event = base(item)
    set_field(event, 'event_name', name, snippet=heading.get_text(' ', strip=True))
    for field, value in [('start_date', matched[1]), ('end_date', matched[2])]:
        if value:
            y, m, d = map(int, value.split('-'))
            set_field(event, field, f'{y:04}-{m:02}-{d:02}', snippet='活动日期 ' + dates,
                      confidence=0.9, method='official_labelled_activity_date')
    # Multi-venue tournaments are not one invented venue reference.
    multiple = bool(re.search(r'、|以及|等场地', place))
    set_field(event, 'location', place, snippet='活动地点 ' + place, confidence=0.85,
              status='Needs Review' if multiple else 'Unverified', method='official_labelled_activity_location')
    if not multiple:
        venue = re.sub(r'[（(]部分图片.*$', '', place).strip()
        set_field(event, 'venue', venue, snippet='活动地点 ' + place, confidence=0.85)
    set_field(event, 'category', category(name), snippet=name, confidence=0.6,
              status='Needs Review', method='event_category_rule')
    # No organiser, street address, business district or coordinates are inferred.
    return event
