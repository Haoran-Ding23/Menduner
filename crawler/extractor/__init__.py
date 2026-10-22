"""Deterministic, AI-ready extraction. Publication dates never become event dates."""

import hashlib
import html
import json
import re
import unicodedata
from bs4 import BeautifulSoup
from crawler.schema import CollectedItem


def text(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Text field must be string or null")
    return (
        re.sub(
            r"\s+",
            " ",
            re.sub(
                r"[\u200b-\u200d\ufeff]",
                "",
                unicodedata.normalize("NFKC", html.unescape(value)),
            ),
        ).strip()
        or None
    )


def claim(
    value,
    *,
    snippet=None,
    confidence=0.85,
    status="Unverified",
    method="explicit_source_field",
):
    return {
        "confidence": confidence if value is not None else 0.0,
        "status": status if value is not None else "Missing",
        "snippet": snippet,
        "method": method,
    }


def base(item):
    fields = (
        "event_name",
        "category",
        "start_date",
        "end_date",
        "venue",
        "location",
        "organizer",
        "venue_id",
        "district_id",
    )
    event = {k: None for k in fields}
    event["category"] = "others"
    event.update(
        event_id="evt-"
        + hashlib.sha256((item.source_name + "|" + item.item_key).encode()).hexdigest()[
            :24
        ],
        source_url=item.original_url,
    )
    event["field_evidence"] = {k: claim(None) for k in fields}
    event["field_evidence"]["source_url"] = claim(
        item.original_url,
        snippet=item.original_url,
        confidence=1.0,
        method="HTTP_response_URL (not fact verification)",
    )
    return event


def set_field(event, key, value, snippet=None, **quality):
    event[key] = text(value)
    event["field_evidence"][key] = claim(
        event[key], snippet=snippet or value, **quality
    )


def full_date(value):
    if not isinstance(value, str):
        return None
    match = re.match(r"^(\d{4})[-./](\d{1,2})[-./](\d{1,2})", value.strip())
    return (
        f"{int(match[1]):04}-{int(match[2]):02}-{int(match[3]):02}" if match else None
    )


def label_organizer(body):
    match = re.search(r"(?:主办单位|主办方)\s*[:：]\s*([^\n]{2,80})", body)
    if not match:
        match = re.search(r"由([^。\n]{2,60}?)主办", body)
    return text(match[1]) if match else None


# --- 太仓市文体广电和旅游局 展讯 -------------------------------------------------
#
# These notices print the two fields the calendar needs as labelled lines, which is why they
# are worth a dedicated extractor rather than a generic article parse:
#
#     展览日期： 2026.10.20 — 11.20
#     展览地点：太仓美术馆 4 号展厅
#
# Three date spellings occur in the live archive and all three must parse, or a third of the
# notices silently vanish:
#     2026.10.20 — 11.20
#     2026 年 9 月 30 日 —11 月 22 日
#     2026.09.22—10.07
_TC_DATED_FIELD = re.compile(
    r"(?:展览日期|展览时间|展出日期|展出时间|活动日期|活动时间|开展时间|展期)"
    r"\s*[:：]\s*([^\n。；;]{5,90})")
_TC_DATE_RANGE = re.compile(
    r"(?P<y1>20\d{2})\s*[.\-/年]\s*(?P<m1>\d{1,2})\s*[.\-/月]\s*(?P<d1>\d{1,2})\s*[日号]?"
    r"\s*[—\-~～至到]+\s*"
    r"(?:(?P<y2>20\d{2})\s*[.\-/年]\s*)?(?:(?P<m2>\d{1,2})\s*[.\-/月]\s*)?"
    r"(?P<d2>\d{1,2})\s*[日号]?")
# A second notice in the archive writes the range without any year: 8 月 22 日至 9 月 20 日.
_TC_DATE_RANGE_NO_YEAR = re.compile(
    r"(?P<m1>\d{1,2})\s*[.\-/月]\s*(?P<d1>\d{1,2})\s*[日号]?\s*[—\-~～至到]+\s*"
    r"(?:(?P<m2>\d{1,2})\s*[.\-/月]\s*)?(?P<d2>\d{1,2})\s*[日号]?")
_TC_VENUE_FIELD = re.compile(
    r"(?:展览地点|展出地点|活动地点|展览场馆|场地)\s*[:：]\s*([^\n]{2,60})")
# A labelled line runs until the next labelled line. The notice writes several of them in one
# paragraph, so the field has to be cut at the next label or it swallows the following field -
# which is how a venue first came out as "太仓美术馆 简介:以书法艺术回望长征…".
_TC_NEXT_LABEL = re.compile(
    r"(?:简介|主办单位|主办方|承办单位|协办单位|支持单位|指导单位|展览日期|展览时间|"
    r"展出日期|展出时间|展览地点|展出地点|活动时间|活动地点|开展时间|展期|扫一扫|预约|"
    r"票价|咨询电话)\s*[:：]")
# 展厅/展区/楼层的 appended detail is part of the room, not of the venue's name. The numeral
# belongs to it too: without it 太仓市博物馆一楼 1 号临展厅 was stripped from 楼 onwards and left
# the venue named 太仓市博物馆一.
_TC_ROOM_SUFFIX = re.compile(
    r"\s*(?:[一二三四五六七八九十两\d]+\s*号?\s*)?"
    r"(?:楼|层|展厅|展区|展馆|会议室|多功能厅|报告厅|厅|室).*$")
# "太仓名人馆(太仓市太平南路 38 号)" - the parenthetical is an address, not part of the name.
_TC_ADDRESS_PAREN = re.compile(r"\s*[（(][^）)]*(?:路|街|镇|道|号)[^）)]*[）)]\s*$")

_TC_PUBLISHED = re.compile(r"时间\s*[:：]\s*(20\d{2})-(\d{1,2})-(\d{1,2})")

_TITLE_PREFIX = re.compile(r"^(?:展讯|展览|预告|通知|活动预告)\s*[丨｜|:：、]\s*")


def _tc_clean_field(raw):
    """A labelled field's value, cut at the next label and stripped of trailing clauses."""
    if not raw:
        return None
    cut = _TC_NEXT_LABEL.search(raw)
    value = raw[:cut.start()] if cut else raw
    value = re.sub(r"\s+", " ", value).strip(" :：,，、。;；")
    return value or None


def _tc_venue(raw):
    value = _tc_clean_field(raw)
    if not value:
        return None, None
    location = value
    name = _TC_ADDRESS_PAREN.sub("", value)
    name = _TC_ROOM_SUFFIX.sub("", name)
    # A room list can precede the room word ("3 、 4 号展厅"), so stripping from the room word
    # leaves the room numbers behind. Trailing floor/room numbers and separators belong to the
    # room, not to the venue.
    name = re.sub(r"[\s、,，/;；和及]+$", "", name)
    name = re.sub(r"(?:\s*\d+\s*[号、,，/]?)+\s*$", "", name)
    name = re.sub(r"[\s、,，/;；和及]+$", "", name).strip()
    name = name or value
    # Some notices wrap the venue in a sentence, and the label cut stops too late: one came out
    # as 太仓美术馆 *因其他展览还在布展阶段…. A venue name is a short proper noun, so anything
    # that still carries prose or markup is refused rather than published as a new venue - a
    # wrong venue is worse than a missing one, because it silently creates a place that does
    # not exist and its events attach to it.
    if len(name) > 20 or re.search(r"[*＊:：，。!！?？;；]|本次|展览|展期|因其他|开放时间", name):
        return None, location
    return name, location


def _tc_dates(text_value, published=None):
    """Start and end date from a 展讯 date line, or (None, None).

    The year appears once in the short form, so ``2026.10.20 — 11.20`` borrows it for the end.
    A range without any year at all (``8 月 22 日至 9 月 20 日``) takes the year the notice was
    published, which is the only year the page states. A range that would end before it starts
    has crossed a year boundary, so the end gets one added year rather than being recorded
    before its own start.
    """
    match = _TC_DATE_RANGE.search(text_value or "")
    if not match:
        return None, None
    if not match["y1"]:
        return None, None
    y1, m1, d1 = int(match["y1"]), int(match["m1"]), int(match["d1"])
    y2 = int(match["y2"]) if match["y2"] else y1
    m2 = int(match["m2"]) if match["m2"] else m1
    d2 = int(match["d2"])
    start = f"{y1:04}-{m1:02}-{d1:02}"
    if y2 == y1 and not match["y2"] and (m2, d2) < (m1, d1):
        y2 += 1
    end = f"{y2:04}-{m2:02}-{d2:02}"
    return start, end


def _tc_dates_without_year(text_value, published_year):
    """A yearless range resolved against the year the notice was published.

    ``8 月 22 日至 9 月 20 日`` states two months but no year, and refusing the notice would
    drop a real exhibition from a source that otherwise supplies dates. The publication year is
    printed on the same page, so it is used and the method says so, instead of inventing one.
    """
    match = _TC_DATE_RANGE_NO_YEAR.search(text_value or "")
    if not match or not published_year:
        return None, None, None
    m1, d1 = int(match["m1"]), int(match["d1"])
    m2 = int(match["m2"]) if match["m2"] else m1
    d2 = int(match["d2"])
    year = int(published_year)
    start = f"{year:04}-{m1:02}-{d1:02}"
    if (m2, d2) < (m1, d1):
        year += 1
    end = f"{year:04}-{m2:02}-{d2:02}"
    return start, end, year


def taicang_culture(item):
    """A 展讯 published by 太仓市文体广电和旅游局, with its stated dates and venue.

    Both fields come from labelled lines in the notice, so they are stated by the publishing
    bureau rather than inferred from prose. A notice without a parseable date range is refused
    instead of published undated: the article would then sit in the calendar under whatever
    month the reader happened to be looking at, which is worse than not being listed.
    """
    soup = BeautifulSoup(item.raw_content, "html.parser")
    body = soup.select_one("#zoomcon") or soup.select_one(".article_content")
    heading = soup.select_one("h1")
    if not body or not heading:
        raise ValueError("Taicang culture article selectors missing; no event invented")

    title = text(heading.get_text(" ", strip=True))
    if not title:
        raise ValueError("Taicang culture article has no title")
    name = _TITLE_PREFIX.sub("", title).strip()
    # Flatten the notice to one line: the CMS puts each labelled field in its own element, but
    # also breaks a field's own value across elements, so a newline inside "2026.10.20 — 11.20"
    # would split the range. Fields are separated afterwards by their labels instead.
    body_text = re.sub(r"\s+", " ", body.get_text(" ", strip=True))
    # The CMS also spaces out digits inside dates - "1 月 1 5 日" is 1月15日 - so digits are
    # rejoined before anything parses them, while the space before 月/日 is left alone.
    body_text = re.sub(r"(?<=\d)\s+(?=\d)", "", body_text)

    published = _TC_PUBLISHED.search(body_text) or _TC_PUBLISHED.search(
        soup.get_text(" ", strip=True))
    published_year = published.group(1) if published else None

    dated = _TC_DATED_FIELD.search(body_text)
    if not dated:
        raise ValueError("No exhibition date line in this Taicang culture notice")
    start, end = _tc_dates(dated.group(1))
    method = "taicang_culture_labelled_date_line"
    if not start:
        start, end, _used = _tc_dates_without_year(dated.group(1), published_year)
        method = "taicang_culture_labelled_date_line + publication year (range states no year)"
    if not start:
        raise ValueError(
            f"Exhibition date line did not yield a date range: {dated.group(1)[:60]}")

    event = base(item)
    set_field(
        event, "event_name", name, snippet=title,
        confidence=0.8, status="Needs Review",
        method="taicang_culture_headline_to_event_name",
    )
    set_field(
        event, "category", "culture", snippet=title,
        confidence=0.7, status="Needs Review", method="event_category_rule",
    )
    set_field(
        event, "start_date", start, snippet=dated.group(0),
        confidence=0.85, status="Needs Review", method=method,
    )
    set_field(
        event, "end_date", end, snippet=dated.group(0),
        confidence=0.85, status="Needs Review", method=method,
    )

    venue_line = _TC_VENUE_FIELD.search(body_text)
    if venue_line:
        venue_name, location = _tc_venue(venue_line.group(1))
        if venue_name:
            set_field(
                event, "venue", venue_name, snippet=venue_line.group(0),
                confidence=0.8, status="Needs Review",
                method="taicang_culture_labelled_venue_line",
            )
            set_field(
                event, "location", location,
                snippet=venue_line.group(0),
                confidence=0.7, status="Needs Review",
                method="taicang_culture_labelled_venue_line (not street-address enrichment)",
            )

    organizer_match = re.search(
        r"(?:主办单位|主办方)\s*[:：]\s*([^\n]{2,80})", body_text)
    if organizer_match:
        organizer = _tc_clean_field(organizer_match.group(1))
        if organizer:
            set_field(
                event, "organizer", organizer, snippet=organizer_match.group(0),
                confidence=0.7, status="Needs Review", method="labelled organizer",
            )
    return event


def government(item):
    soup = BeautifulSoup(item.raw_content, "html.parser")
    body = soup.select_one("#zoomcon")
    title = soup.select_one("h1") or soup.find("meta", attrs={"name": "ArticleTitle"})
    if not body or not title:
        raise ValueError("Official article selectors missing; no event invented")
    heading = text(title.get("content") or title.get_text(" ", strip=True))
    if not re.search(r"艺术周|光影节|文化节|展览|演出|音乐会|开幕", heading):
        raise ValueError("Page is not a supported event article")
    event = base(item)
    name = re.sub(r"(周六)?(?:启幕|开幕|举行|启动)$", "", heading)
    set_field(
        event,
        "event_name",
        name,
        snippet=heading,
        confidence=0.7,
        status="Needs Review",
        method="article_headline_to_event_name",
    )
    set_field(
        event,
        "category",
        "culture",
        snippet=heading,
        confidence=0.6,
        status="Needs Review",
        method="event_category_rule",
    )
    paragraphs = [
        n.get_text(" ", strip=True)
        for n in body.find_all("p")
        if n.get_text(strip=True)
    ]
    lead = " ".join(paragraphs[:2])
    all_body = body.get_text("\n", strip=True)
    year = re.search(r"(?<!\d)(20\d{2})(?!\d)", heading)
    if year:
        interval = re.search(
            r"(\d{1,2})月(\d{1,2})日\s*(?:至|—|-)\s*(?:(\d{1,2})月)?(\d{1,2})日", lead
        )
        if interval:
            start = f"{year[1]}-{int(interval[1]):02}-{int(interval[2]):02}"
            end = (
                f"{year[1]}-{int(interval[3] or interval[1]):02}-{int(interval[4]):02}"
            )
            snippet = interval[0]
        else:
            opening = re.search(r"(\d{1,2})月(\d{1,2})日", lead)
            finish = re.search(r"持续至\s*(\d{1,2})月(\d{1,2})日", lead)
            start = (
                f"{year[1]}-{int(opening[1]):02}-{int(opening[2]):02}"
                if opening
                else None
            )
            end = (
                f"{year[1]}-{int(finish[1]):02}-{int(finish[2]):02}" if finish else None
            )
            snippet = lead[:280]
        set_field(
            event,
            "start_date",
            start,
            snippet=snippet,
            confidence=0.75,
            status="Needs Review",
            method="body_month_day + explicit_event_year_in_headline",
        )
        set_field(
            event,
            "end_date",
            end,
            snippet=snippet,
            confidence=0.75,
            status="Needs Review",
            method="body_end_month_day + explicit_event_year_in_headline",
        )
    place = re.search(r"在([^。\n]{3,55}?)(?:启幕|开幕|举行|设立)", lead)
    if place:
        location = text(place[1])
        venue = re.sub(r"^国家5A级景区", "", location)
        venue = re.sub(r"^苏州工业园区", "", venue)
        set_field(
            event,
            "venue",
            venue,
            snippet=place[0],
            confidence=0.7,
            status="Needs Review",
            method="body_place_phrase",
        )
        set_field(
            event,
            "location",
            location,
            snippet=place[0],
            confidence=0.7,
            status="Needs Review",
            method="body_place_phrase (not street-address enrichment)",
        )
    organizer = label_organizer(all_body)
    set_field(event, "organizer", organizer, snippet=organizer, confidence=0.8)
    return event


def orchestra(item):
    document = json.loads(item.raw_content)
    row = next(
        (r for r in document.get("content", []) if str(r.get("id")) == item.locator),
        None,
    )
    if not row:
        raise ValueError("Public schedule item not found")
    if row.get("deleted") or row.get("available") is False:
        raise ValueError("Unavailable/deleted performance: retained raw, not published")
    event = base(item)
    set_field(event, "event_name", row.get("title"), snippet=row.get("title"))
    set_field(
        event,
        "category",
        "culture",
        snippet="official performance programme",
        confidence=0.6,
        status="Needs Review",
        method="category_rule",
    )
    attributes = row.get("attributeMapSingle") or {}
    time_value = (attributes.get("time") or {}).get("value")
    set_field(
        event,
        "start_date",
        full_date(time_value),
        snippet="attributeMapSingle.time.value=" + str(time_value),
        confidence=0.9,
        method="explicit_performance_datetime",
    )
    content = BeautifulSoup(
        html.unescape(row.get("content") or ""), "html.parser"
    ).get_text("\n", strip=True)
    header = "\n".join(content.splitlines()[:10])
    body_dates = {
        full_date(m[0]) for m in re.finditer(r"20\d{2}[-./]\d{1,2}[-./]\d{1,2}", header)
    }
    typed = event["start_date"]
    if typed and body_dates and typed not in body_dates:
        event["start_date"] = None
        event["field_evidence"]["start_date"] = dict(
            confidence=0.4,
            status="Needs Review",
            method="within_source_date_conflict",
            snippet="attributeMapSingle.time.value="
            + str(time_value)
            + "; body header="
            + header[:300],
            candidates=sorted(body_dates | {typed}),
        )
    # A presentation template's hardcoded hall is NOT venue evidence. Use this record's body.
    venue = next(
        (
            line
            for line in content.splitlines()
            if re.fullmatch(r"苏州[^\n]{1,60}(?:大剧院|剧院|音乐厅)", line.strip())
        ),
        None,
    )
    if not venue:
        address = (attributes.get("address") or {}).get("value")
        if isinstance(address, str) and re.fullmatch(
            r"苏州.{1,50}(?:剧院|音乐厅)", address
        ):
            venue = address
    set_field(event, "venue", venue, snippet=venue)
    set_field(event, "organizer", label_organizer(content), confidence=0.8)
    # endDate, street location and organizer stay null unless explicitly present.
    return event


def jsonld(item):
    soup = BeautifulSoup(item.raw_content, "html.parser")
    event_node = None
    for node in soup.select('script[type="application/ld+json"]'):
        document = json.loads(node.get_text())
        nodes = (
            document.get("@graph", [document])
            if isinstance(document, dict)
            else document
        )
        for candidate in nodes:
            kind = candidate.get("@type", [])
            kind = [kind] if isinstance(kind, str) else kind
            if any(
                k in ("Event", "MusicEvent", "TheaterEvent", "ExhibitionEvent")
                for k in kind
            ):
                event_node = candidate
                break
        if event_node:
            break
    if not event_node:
        raise ValueError("No event JSON-LD in public detail page")
    if "Cancelled" in str(event_node.get("eventStatus", "")):
        raise ValueError("Cancelled event: retained raw, not published")
    location = event_node.get("location")
    if (
        not isinstance(location, dict)
        or "Suzhou" not in json.dumps(location, ensure_ascii=False)
        and "苏州" not in json.dumps(location, ensure_ascii=False)
    ):
        raise ValueError("JSON-LD event location is not explicitly Suzhou")
    event = base(item)
    set_field(
        event,
        "event_name",
        event_node.get("name"),
        snippet="JSON-LD.name=" + str(event_node.get("name")),
    )
    for key, source in [("start_date", "startDate"), ("end_date", "endDate")]:
        set_field(
            event,
            key,
            full_date(event_node.get(source)),
            snippet="JSON-LD." + source + "=" + str(event_node.get(source)),
            confidence=0.9,
            method="JSON-LD.event_datetime",
        )
    set_field(
        event,
        "venue",
        location.get("name"),
        snippet="JSON-LD.location.name=" + str(location.get("name")),
    )
    address = location.get("address")
    address = address.get("streetAddress") if isinstance(address, dict) else address
    set_field(
        event, "location", address, snippet="JSON-LD.location.address=" + str(address)
    )
    organizer = event_node.get("organizer")
    organizer = organizer.get("name") if isinstance(organizer, dict) else organizer
    set_field(
        event, "organizer", organizer, snippet="JSON-LD.organizer=" + str(organizer)
    )
    set_field(
        event,
        "category",
        "culture",
        snippet="JSON-LD.@type=" + str(event_node.get("@type")),
        confidence=0.6,
        status="Needs Review",
        method="category_rule",
    )
    return event


def extract(item: CollectedItem, kind: str):
    if item.mock:
        from crawler.demo.extractor import extract as demo_extract

        return demo_extract(item, kind)
    if not item.is_event:
        raise ValueError("Context page is not an event")
    from crawler.extractor.cityevent import article, olympic
    from crawler.extractor.damai import damai_public_event
    from crawler.sources.event_platform.huodongjia import huodongjia_event
    from crawler.sources.tourism.visitsz import visitsz_event
    from crawler.sources.community.douban import douban_event
    from crawler.sources.community.xiaohongshu import social_note_ai
    from crawler.sources.exhibition.cnena import cnena_exhibition
    from crawler.sources.exhibition.haozhanhui import haozhanhui_exhibition
    from crawler.sources.venue.expo import expo_exhibition
    from crawler.sources.venue.sscac import sscac_performance

    parsers = {
        "government_article": government,
        "orchestra_json": orchestra,
        "jsonld": jsonld,
        "official_article_v16": article,
        "media_article_v16": article,
        "olympic_detail": olympic,
        "damai_public_event": damai_public_event,
        "huodongjia_ssr": huodongjia_event,
        "visitsz_detail": visitsz_event,
        "douban_event": douban_event,
        "social_note_ai": social_note_ai,
        "cnena_exhibition": cnena_exhibition,
        "haozhanhui_exhibition": haozhanhui_exhibition,
        "expo_exhibition": expo_exhibition,
        "sscac_performance": sscac_performance,
        "taicang_culture": taicang_culture,
    }
    if item.extractor not in parsers:
        raise ValueError("Unsupported real extractor")
    return parsers[item.extractor](item)
