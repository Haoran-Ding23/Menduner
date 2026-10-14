"""Resolve a pasted AMap coordinate to the AMap place it sits on.

Why: the coordinate-entry form used to demand a source URL, but AMap's own web UI has no stable
per-place URL — it is a query string — so a reviewer had no URL to give and every entry was
blocked on a field they could not fill. The provenance can be recovered from the coordinate:

    coordinate -> regeo (the formatted address AMap itself states)
               -> search that address -> the POI whose position matches the coordinate

The matched POI gives a stable ``ditu.amap.com/place/<id>`` URL. When nothing matches within a
few metres the coordinate is still usable — it is simply recorded as a human-placed coordinate
with no AMap place behind it, which is honest and still reviewable.
"""
from __future__ import annotations

import math
import os
from pathlib import Path

import httpx

REGO_ENDPOINT = "https://restapi.amap.com/v3/geocode/regeo"
POI_ENDPOINT = "https://restapi.amap.com/v3/place/text"
PLACE_URL = "https://ditu.amap.com/place/"
# The POI must be the thing at that spot, not merely nearby.
MATCH_METRES = 60.0
TIMEOUT = 15.0


def _key() -> str | None:
    key = os.environ.get("AMAP_WEBSERVICE_KEY")
    if key:
        return key.strip()
    env_file = Path(__file__).resolve().parent.parent / "frontend" / ".env.local"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("AMAP_WEBSERVICE_KEY="):
                return line.split("=", 1)[1].strip()
    return None


def _metres(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lng1 = a
    lat2, lng2 = b
    dl = math.radians(lat2 - lat1)
    dn = math.radians(lng2 - lng1)
    h = (
        math.sin(dl / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dn / 2) ** 2
    )
    return 6371000 * 2 * math.asin(math.sqrt(min(1.0, h)))


def amap_place_url(lng: float, lat: float, *, name_hint: str | None = None) -> str:
    """A stable AMap provenance URL for a coordinate.

    Never raises: a coordinate that cannot be resolved is still a valid human-placed coordinate,
    and it must not be possible for an AMap hiccup to block a review. Falls back to a
    coordinate URL that opens the right spot on AMap.
    """
    fallback = f"https://www.amap.com/regeo?lng={lng}&lat={lat}"
    key = _key()
    if not key:
        return fallback
    location = f"{lng},{lat}"
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            document = client.get(
                REGO_ENDPOINT,
                params={"key": key, "location": location, "extensions": "base", "radius": 200},
            ).json()
            if document.get("status") != "1":
                return fallback
            address = (document.get("regeocode") or {}).get("formatted_address")
            if not isinstance(address, str) or not address:
                return fallback
            pois = client.get(
                POI_ENDPOINT,
                params={
                    "key": key,
                    "keywords": f"{address} {name_hint or ''}".strip(),
                    "city": "苏州",
                    "offset": 10,
                    "page": 1,
                    "extensions": "all",
                },
            ).json()
    except Exception:
        return fallback
    if pois.get("status") != "1":
        return fallback

    best: tuple[float, str] | None = None
    for poi in pois.get("pois") or []:
        raw = poi.get("location")
        if not raw or not poi.get("id"):
            continue
        try:
            poi_lng, poi_lat = (float(x) for x in raw.split(","))
        except ValueError:
            continue
        gap = _metres((lat, lng), (poi_lat, poi_lng))
        if gap > MATCH_METRES:
            continue
        if best is None or gap < best[0]:
            best = (gap, str(poi["id"]))
    return PLACE_URL + best[1] if best else fallback
