"""The street-address part of a source place string, derived deterministically.

Two shapes reach a venue row today, and both are the *source's own* string:

  * 豆瓣同城 place line — space separated, city / district / venue name / street:
    ``苏州 吴中区 山丘livehouse-斜塘店 松涛街1088号斜塘老街36幢``
  * visitsz 地点 line — one run-on string with the venue name repeated at the end:
    ``苏州市吴中区东苑路1号苏州保利大剧院大剧场``

The source's claim itself is never rewritten: the event's ``location`` field keeps the whole
string as published, with its own evidence and snippet. What this module derives is only the
venue row's ``address``, which a human reads on the coordinate-maintenance screen and which the
address resolver sends to AMap — so it keeps the address and drops the administrative prefix and
the repeated venue name:

  ``苏州 吴中区 山丘livehouse-斜塘店 松涛街1088号斜塘老街36幢``  -> ``松涛街1088号斜塘老街36幢``
  ``苏州市吴中区东苑路1号苏州保利大剧院大剧场``                  -> ``东苑路1号``
  ``苏州市工业园区中新大道东999号苏州奥林匹克体育中心体育馆``      -> ``中新大道东999号``

``lookup_address`` reduces the same string further, to the road plus its house number, which is
the form that discriminates one building from another when AMap is asked to find it:

  ``苏州 吴中区 山丘livehouse-斜塘店 松涛街1088号斜塘老街36幢``  -> ``松涛街1088号``

A string with no explicit house number yields ``None``: an address is never invented from a
scenic-area name, a bare road, or a metro station.
"""
from __future__ import annotations

import re

from crawler.extractor import text

# Administrative words that are not part of an address. Suzhou's county-level cities are listed
# because the registry covers 昆山/常熟/太仓/张家港 venues as well as the city itself.
CITY_TOKENS = ("苏州市", "苏州", "昆山市", "常熟市", "太仓市", "张家港市")
DISTRICT_TOKEN = re.compile(r"^[\u4e00-\u9fff]{2,6}(?:区|县|市|镇|新区|开发区)$")
DISTRICT_PREFIX = re.compile(r"^[\u4e00-\u9fff]{2,6}(?:区|县|市|镇|新区|开发区)")
# A named road, an optional direction (中新大道**东**999号) or a lane inside a 街道
# (平江街道皮市街9-69号), then an explicit house number. The number is what makes this an
# address rather than a place name.
ROAD_NUMBER = re.compile(
    r"[\u4e00-\u9fff]{1,12}(?:路|街|巷|弄|大道|大街|公路|道|桥)"
    r"(?:东|西|南|北|中)?[\u4e00-\u9fff]{0,4}?"
    r"\s*\d{1,5}(?:\s*[-—~至]\s*\d{1,5})?\s*号"
)
SEPARATORS = "·・/／-—()（）"


def _normalise(value):
    return text(value) if isinstance(value, str) else None


def _identity(value: str | None) -> str:
    """A name/address comparison key: no spaces, no punctuation, no 苏州 prefix."""
    if not value:
        return ""
    cleaned = "".join(ch for ch in value if not ch.isspace() and ch not in SEPARATORS)
    for prefix in ("苏州市", "苏州"):
        if cleaned.startswith(prefix) and len(cleaned) > len(prefix) + 2:
            return cleaned[len(prefix):]
    return cleaned


def _name_pattern(name: str | None):
    """Regex for the venue's own name inside an address, tolerating its punctuation.

    ``苏州保利大剧院`` matches itself inside ``东苑路1号苏州保利大剧院大剧场``, and
    ``山丘livehouse-斜塘店`` still matches where a source writes a different dash.
    """
    characters = [ch for ch in (_normalise(name) or "") if not ch.isspace() and ch not in SEPARATORS]
    if len(characters) < 2:
        return None
    gap = r"[\s" + re.escape(SEPARATORS) + r"]*"
    return re.compile(gap.join(re.escape(ch) for ch in characters))


def road_number(value: str | None) -> str | None:
    """``松涛街1088号`` — the road and house number inside a place string, else None."""
    normalised = _normalise(value)
    if not normalised:
        return None
    matched = ROAD_NUMBER.search(normalised)
    return re.sub(r"\s+", "", matched.group(0)) if matched else None


def _peel_administrative(value: str) -> str:
    """Drop leading city/district words from a run-on place string.

    ``太仓市半泾南路3号…`` -> ``半泾南路3号…`` and ``苏州市工业园区中新大道东999号…`` ->
    ``中新大道东999号…``. A word is only peeled when something substantial follows it, so a
    source that publishes nothing but an administrative name is left alone (and then yields no
    address at all).
    """
    changed = True
    while changed:
        changed = False
        for token in CITY_TOKENS:
            if value.startswith(token) and len(value) > len(token) + 3:
                value = value[len(token):].lstrip()
                changed = True
                break
        else:
            matched = DISTRICT_PREFIX.match(value)
            if matched and len(value) > len(matched.group(0)) + 3:
                value = value[matched.end():].lstrip()
                changed = True
    return value


def _peeled_tail(normalised: str) -> str:
    """A place string with its leading city/district words removed.

    Spaced place lines lose whole tokens (``苏州 吴中区 | 山丘livehouse-斜塘店 松涛街1088号…``),
    run-on ones lose the same words character-wise (``太仓市半泾南路3号…`` -> ``半泾南路3号…``).
    """
    tail = normalised
    if " " in normalised:
        tokens = [token for token in normalised.split(" ") if token]
        start = 0
        while start < len(tokens):
            token = tokens[start]
            if token in CITY_TOKENS or DISTRICT_TOKEN.match(token):
                start += 1
                continue
            break
        tail = " ".join(tokens[start:])
    return _peel_administrative(tail)


def lookup_address(value: str | None) -> str | None:
    """The address to query a map service with: road plus house number where one exists.

    ``松涛街1088号斜塘老街36幢`` reduces to ``松涛街1088号``. Administrative words are peeled
    first, otherwise the greedy road pattern swallows them (``太仓市半泾南路3号`` would come back
    whole). Falls back to :func:`street_address`, so a caller always gets the most specific
    address the source actually published.
    """
    normalised = _normalise(value)
    if not normalised:
        return None
    return road_number(_peeled_tail(normalised)) or street_address(value)


def street_address(value: str | None, *, venue_name: str | None = None) -> str | None:
    """The address part of a source place string, or None when it publishes none.

    Rules, in order — all deterministic and all recorded in this module's tests:

    1. Leading words that are a city, a district/county, or the venue's own name are dropped
       (``苏州 吴中区 山丘livehouse-斜塘店 | 松涛街1088号斜塘老街36幢``), and a run-on string gets
       the same treatment character-wise (``太仓市半泾南路3号…`` -> ``半泾南路3号…``).
    2. The address starts at the road whose house number the string carries; anything before it
       is administrative text or the venue name repeated.
    3. A repetition of the venue's own name after the address is cut, together with a city word
       it is written with (``观前街北局11号|苏州|开明大戏院大剧场`` -> ``观前街北局11号``).
    4. The result must still contain that road and house number, otherwise there is no address
       to publish.
    """
    normalised = _normalise(value)
    if not normalised:
        return None
    name_key = _identity(_normalise(venue_name))
    tokens = [token for token in _peeled_tail(normalised).split(" ") if token]
    while tokens and name_key and _identity(tokens[0]) == name_key:
        tokens.pop(0)
    tail = " ".join(tokens)
    anchor = ROAD_NUMBER.search(tail)
    if not anchor:
        return None
    address = tail[anchor.start():]
    pattern = _name_pattern(venue_name)
    if pattern is not None:
        # Cut the venue's own name out of the tail, but never the address itself: a match at
        # position 0 is the address being named after the venue, not a repetition of it.
        repeated = pattern.search(address)
        while repeated is not None and repeated.start() > 0:
            address = address[:repeated.start()]
            repeated = pattern.search(address)
    address = address.strip(" ·・/／-—").strip()
    trimmed = True
    while trimmed:
        trimmed = False
        for token in CITY_TOKENS:
            if (address.endswith(token) and len(address) > len(token) + 3
                    and ROAD_NUMBER.search(address[:-len(token)])):
                address = address[:-len(token)].strip(" ·・/／-—").strip()
                trimmed = True
                break
    if not address or not ROAD_NUMBER.search(address):
        return None
    return address


def venue_address(location: str | None, venue_name: str | None = None) -> str | None:
    """The address a venue row should carry, given one of its events' ``location`` claims."""
    return street_address(location, venue_name=venue_name)
