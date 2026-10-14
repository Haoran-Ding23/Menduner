import json
import re
import unicodedata
from crawler.schema import CollectedItem


def text(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Text field must be string or null")
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip() or None


def extract(item: CollectedItem, kind: str):
    row = json.loads(item.raw_content)
    if kind == "government":
        details = row["details"]
        values = dict(
            event_id=row["activity"]["id"],
            event_name=row["activity"]["name"],
            start_date=row["dates"]["start"],
            end_date=row["dates"]["end"],
        )
    elif kind == "venue":
        details = row["details"]
        values = dict(
            event_id=row["event_id"],
            event_name=row["title"],
            start_date=row["begin"],
            end_date=row["finish"],
        )
    elif kind == "event_platform":
        details = row
        values = dict(
            event_id=row["id"],
            event_name=row["name"],
            start_date=row["start"],
            end_date=row["end"],
        )
    else:
        raise ValueError(f"Unsupported extractor: {kind}")
    values.update(
        category=details.get("category", "others"),
        venue=details.get("venue"),
        location=details.get("location"),
        organizer=details.get("organizer"),
        venue_id=details.get("venueId", details.get("venue_id")),
        district_id=details.get("districtId", details.get("district_id")),
        source_url=item.original_url,
    )
    return {key: text(value) for key, value in values.items()}
