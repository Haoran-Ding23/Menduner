"""Strict public Event JSON-LD parser. No script execution or private API data."""
import json
import re
from urllib.parse import urlparse, urljoin, parse_qs
from bs4 import BeautifulSoup

from crawler.extractor import base, text, set_field
from datetime import date as Date, datetime, timezone, timedelta
from crawler.sources.event_platform.public_access import blocked_page

EVENT_TYPES = {'Event', 'MusicEvent', 'TheaterEvent', 'DanceEvent', 'SportsEvent',
               'EducationEvent', 'BusinessEvent', 'ExhibitionEvent', 'Festival'}
CITY_ALIASES = {'苏州', '苏州市', 'suzhou', 'suzhou city'}


def public_date(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    try:
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            return Date.fromisoformat(value).isoformat()
        if re.match(r'^\d{4}-\d{2}-\d{2}T', value):
            timestamp = datetime.fromisoformat(value)
            if timestamp.tzinfo is not None:
                timestamp = timestamp.astimezone(timezone(timedelta(hours=8)))  # Suzhou; works without Windows IANA data.
            return timestamp.date().isoformat()
    except ValueError:
        pass
    return None


def damai_public_event(item):
    from crawler.sources.event_platform.damai import DamaiSource
    if urlparse(item.original_url).hostname != 'detail.damai.cn' or not DamaiSource.is_public_url(item.original_url):
        raise ValueError('Damai event data must come from the approved public detail host')
    if blocked_page(item.raw_content):
        raise ValueError('Login/CAPTCHA/access wall: raw retained, no event published')
    soup = BeautifulSoup(item.raw_content, 'html.parser')
    events = []
    for script in soup.select('script[type="application/ld+json"]'):
        document = json.loads(script.get_text())
        nodes = document.get('@graph', [document]) if isinstance(document, dict) else document
        if not isinstance(nodes, list):
            raise ValueError('Unsupported public JSON-LD structure')
        for node in nodes:
            if not isinstance(node, dict):
                continue
            kinds = node.get('@type', [])
            kinds = [kinds] if isinstance(kinds, str) else kinds
            kinds = {str(k).rsplit('/', 1)[-1] for k in kinds}
            if kinds & EVENT_TYPES:
                events.append((node, kinds))
    if len(events) != 1:
        raise ValueError('Expected one complete public Event JSON-LD record; no API fallback')
    node, kinds = events[0]
    if node.get('url') is not None:
        if not isinstance(node['url'], str):
            raise ValueError('Event canonical URL is not a public URL string')
        canonical = urljoin(item.original_url, node['url']).split('#', 1)[0]
        if (not DamaiSource.is_public_url(canonical)
                or urlparse(canonical).hostname != 'detail.damai.cn'
                or parse_qs(urlparse(canonical).query)['id'] != parse_qs(urlparse(item.original_url).query)['id']):
            raise ValueError('Event canonical URL does not match the requested public item')
    if re.search(r'Cancelled|Postponed', str(node.get('eventStatus', '')), re.I):
        raise ValueError('Cancelled/postponed event: raw retained, no guessed date')
    name = text(node.get('name'))
    date = public_date(node.get('startDate'))
    location = node.get('location')
    if not name or not date or not isinstance(location, dict):
        raise ValueError('Public event name/date/location incomplete; sale dates are not event dates')
    venue = text(location.get('name'))
    address = location.get('address')
    city = text(address.get('addressLocality')) if isinstance(address, dict) else None
    if not venue or not city or city.casefold() not in CITY_ALIASES:
        raise ValueError('Explicit Suzhou city and named venue required; title alone is not city evidence')
    event = base(item)
    set_field(event, 'event_name', name, snippet='JSON-LD.name=' + str(node.get('name')), confidence=0.9)
    set_field(event, 'start_date', date, snippet='JSON-LD.startDate=' + str(node.get('startDate')),
              confidence=0.9, method='public_JSON-LD_event_date (not sale time)')
    if node.get('endDate') is not None:
        finish = public_date(node['endDate'])
        if not finish:
            raise ValueError('Explicit end date cannot be reliably parsed')
        set_field(event, 'end_date', finish, snippet='JSON-LD.endDate=' + str(node['endDate']), confidence=0.9)
    set_field(event, 'venue', venue, snippet='JSON-LD.location.name=' + str(location.get('name')), confidence=0.9)
    set_field(event, 'city', '苏州', snippet='JSON-LD.location.address.addressLocality=' + city,
              confidence=0.9, method='explicit_source_city_alias_normalization')
    if isinstance(address, dict):
        set_field(event, 'location', address.get('streetAddress'),
                  snippet='JSON-LD.location.address.streetAddress=' + str(address.get('streetAddress')), confidence=0.85)
    category = ('sports' if 'SportsEvent' in kinds else 'education' if 'EducationEvent' in kinds else
                'business' if kinds & {'BusinessEvent', 'ExhibitionEvent'} else
                'culture' if kinds & {'MusicEvent', 'TheaterEvent', 'DanceEvent', 'Festival'} else 'others')
    set_field(event, 'category', category, snippet='JSON-LD.@type=' + str(node.get('@type')),
              confidence=0.6, status='Needs Review', method='source_event_type_to_category_rule')
    organizer = node.get('organizer')
    if isinstance(organizer, dict):
        set_field(event, 'organizer', organizer.get('name'), snippet='JSON-LD.organizer.name=' + str(organizer.get('name')), confidence=0.85)
    return event
