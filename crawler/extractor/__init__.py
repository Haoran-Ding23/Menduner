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
    from crawler.sources.exhibition.cnena import cnena_exhibition

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
        "cnena_exhibition": cnena_exhibition,
    }
    if item.extractor not in parsers:
        raise ValueError("Unsupported real extractor")
    return parsers[item.extractor](item)
