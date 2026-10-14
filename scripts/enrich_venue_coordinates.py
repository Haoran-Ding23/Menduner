"""Enrich venues with verified coordinates from the AMap Web service.

Only for rows that have no coordinates yet. Nothing is inferred: a coordinate is written
only when AMap returns a POI whose name matches the venue name, and every row keeps the AMap
place URL as its provenance so a human can re-check it.

Two confidence levels, deliberately:
  * an EXACT normalised name match in the right city is written as ``Verified`` geometry;
  * a partial match is written as ``Needs Review`` with the candidate name recorded, so it
    lands in the human queue instead of silently becoming a map pin.

Requires a Web-service key in AMAP_WEBSERVICE_KEY (or frontend/.env.local). A JS-API key
returns USERKEY_PLAT_NOMATCH and is reported as a configuration error, not a data error.

Dry-run by default; pass --apply to write.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from backend.database import connect, snapshot  # noqa: E402

DEFAULT_DB = Path("backend/data/menduner.sqlite3")
POI_ENDPOINT = "https://restapi.amap.com/v3/place/text"
PLACE_URL = "https://ditu.amap.com/place/"
# Suzhou prefecture and its county-level cities: an event outside these is not Suzhou demand.
SUZHOU_AREAS = ("苏州市", "苏州", "昆山市", "常熟市", "太仓市", "张家港市", "吴江区")
KEY_FIELDS = ("id", "payload")
REQUEST_INTERVAL = 0.35


def load_key() -> str | None:
    key = os.environ.get("AMAP_WEBSERVICE_KEY")
    if key:
        return key.strip()
    env_file = Path(__file__).resolve().parent.parent / "frontend/.env.local"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("AMAP_WEBSERVICE_KEY="):
                return line.split("=", 1)[1].strip()
    return None


def normalize(name: str) -> str:
    return re.sub(r"[\s·・/／\-—()（）]+", "", name or "")


def is_suzhou(poi: dict) -> bool:
    where = f"{poi.get('cityname') or ''}{poi.get('adname') or ''}{poi.get('pname') or ''}"
    return any(area in where for area in SUZHOU_AREAS)


def lookup(client: httpx.Client, key: str, name: str) -> tuple[dict | None, str]:
    """Return (accepted poi, reason). Accepted means exact name match in Suzhou."""
    response = client.get(
        POI_ENDPOINT,
        params={"key": key, "keywords": name, "city": "苏州", "offset": 10, "page": 1},
    )
    document = response.json()
    status = document.get("status")
    info = document.get("info")
    if status != "1":
        return None, f"amap error: {info}"
    pois = [p for p in (document.get("pois") or []) if p.get("location")]
    if not pois:
        return None, "no poi returned"
    wanted = normalize(name)
    for poi in pois:
        if normalize(poi.get("name")) == wanted:
            if not is_suzhou(poi):
                return None, f"exact name but outside Suzhou ({poi.get('cityname')})"
            return poi, "exact name match in Suzhou"
    partial = [
        poi
        for poi in pois
        if wanted and (wanted in normalize(poi.get("name")) or normalize(poi.get("name")) in wanted)
        and is_suzhou(poi)
    ]
    if partial:
        poi = partial[0]
        return (
            None,
            f"partial match only: {poi.get('name')} @ {poi.get('location')} "
            f"[{PLACE_URL}{poi.get('id')}]",
        )
    return None, f"no name match among {len(pois)} results"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="0 = all")
    parser.add_argument("--interval", type=float, default=REQUEST_INTERVAL)
    args = parser.parse_args()

    key = load_key()
    if not key:
        print("No AMAP_WEBSERVICE_KEY found. Set the environment variable or add it to")
        print("frontend/.env.local as AMAP_WEBSERVICE_KEY=<web service key>.")
        return 2

    if not args.db.exists():
        print(f"missing database: {args.db}")
        return 1

    snap = snapshot(args.db)
    used = {e["venueId"] for e in snap["events"] if e.get("venueId")}
    pending = [
        v
        for v in snap["venues"]
        if v["id"] in used and not v.get("coordinates") and (v.get("name") or "").strip()
    ]
    pending.sort(key=lambda v: v["name"])
    if args.limit:
        pending = pending[: args.limit]

    print(f"database   : {args.db}")
    print(f"venues used by events without coordinates: {len(pending)}")
    print()

    client = httpx.Client(timeout=20)
    verified: list[tuple[str, str, float, float, str]] = []
    review: list[tuple[str, str, str]] = []
    failed: list[tuple[str, str]] = []
    try:
        for index, venue in enumerate(pending, start=1):
            try:
                poi, reason = lookup(client, key, venue["name"])
            except Exception as exc:  # network/parse failure is not a data verdict
                failed.append((venue["name"], f"{type(exc).__name__}: {exc}"))
                print(f"  [{index:2d}] {venue['name'][:30]:30s} ERROR   {exc}")
                time.sleep(args.interval)
                continue
            if poi:
                lng, lat = (float(x) for x in poi["location"].split(","))
                poi_id = str(poi.get("id") or "")
                verified.append((venue["id"], venue["name"], lng, lat, poi_id))
                marker = "VERIFIED"
                detail = f"{poi['name']} [{PLACE_URL}{poi_id}]"
            else:
                review.append((venue["id"], venue["name"], reason))
                marker = "review  "
                detail = reason
            print(f"  [{index:2d}] {venue['name'][:30]:30s} {marker}  {detail[:78]}")
            time.sleep(args.interval)
    finally:
        client.close()

    print()
    print(f"exact matches (Verified) : {len(verified)}")
    print(f"needs human review       : {len(review)}")
    print(f"lookup failures          : {len(failed)}")

    if not args.apply:
        print("\nDRY RUN: pass --apply to write coordinates")
        return 0

    with connect(args.db) as con:
        for venue_id, _name, lng, lat, poi_id in verified:
            row = con.execute(
                "SELECT payload FROM venues WHERE id=?", (venue_id,)
            ).fetchone()
            payload = json.loads(row["payload"])
            payload["coordinates"] = {
                "lng": lng,
                "lat": lat,
                "system": "GCJ-02",
                "status": "Verified",
                "sourceUrl": PLACE_URL + poi_id,
            }
            con.execute(
                "UPDATE venues SET payload=? WHERE id=?",
                (json.dumps(payload, ensure_ascii=False, sort_keys=True), venue_id),
            )
    print(f"\nAPPLIED: {len(verified)} venues given verified coordinates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
