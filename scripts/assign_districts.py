"""Assign Suzhou business districts to venues and their events by AMap reverse geocoding.

An administrative district is far too coarse to be useful here: 吴中区 alone contains 苏州国际
博览中心, 文化艺术中心 and 金鸡湖, so a single "吴中区 92 个活动" row swallowed most of the
city's demand. AMap's reverse geocoding exposes two finer levels and both are real data:

  * ``businessAreas`` — the commercial districts a local would name (观前, 南门, 双塔, 湖东);
  * ``township`` — the sub-district (街道/镇), e.g. 金鸡湖街道, 平江街道.

A venue is placed in its business area when AMap names one, otherwise in its sub-district, and
the kind is recorded with the row so the map never implies a commercial district it does not
have. Venues whose name cannot be matched to an AMap place are NOT guessed at; their events go
to an explicit "未归入商圈" row.

Dry-run by default; pass --apply to write. Requires AMAP_WEBSERVICE_KEY.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from backend.database import connect, snapshot  # noqa: E402

DEFAULT_DB = Path("backend/data/menduner.sqlite3")
REGO_URL = "https://restapi.amap.com/v3/geocode/regeo"
POI_URL = "https://restapi.amap.com/v3/place/text"
PLACE_URL = "https://ditu.amap.com/place/"
UNASSIGNED = "district-unassigned"
SUZHOU_AREAS = ("苏州市", "昆山市", "常熟市", "太仓市", "张家港市")


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


def district_id(name: str) -> str:
    """Stable id for an administrative district, derived from its name."""
    return "district-" + name


def bare(name: str) -> str:
    """Identity form of a venue name: no punctuation, no city/district prefix."""
    cleaned = "".join(ch for ch in name if ch not in " ·・/／-—()（）")
    for prefix in ("苏州市", "苏州", "昆山市", "常熟市", "太仓市", "张家港市"):
        if cleaned.startswith(prefix) and len(cleaned) > len(prefix) + 2:
            cleaned = cleaned[len(prefix):]
            break
    return cleaned


def locate_missing(client: httpx.Client, key: str, name: str) -> tuple[float, float, str] | None:
    """Find a venue that has no stored coordinate, by its name.

    Only used to place the event in the right administrative district, never to write a
    coordinate. Matching is deliberately conservative, because a wrong district is worse than
    an honest "unassigned":

      exact   same name after normalisation, ignoring a city/district prefix;
      suffix  a candidate of comparable length is a suffix of the venue name.

    Abbreviations are NOT matched (``苏州奥体中心体育馆`` vs ``苏州奥林匹克体育中心-体育馆``),
    which is why some venues remain unassigned.
    """
    response = client.get(
        POI_URL,
        params={"key": key, "keywords": name, "offset": 10, "page": 1},
    )
    document = response.json()
    if document.get("status") != "1":
        return None
    wanted = bare(name)
    if len(wanted) < 3:
        return None
    best: tuple[str, float, float] | None = None
    for poi in document.get("pois") or []:
        raw = poi.get("name") or ""
        candidate = bare(raw)
        if not candidate or not poi.get("location"):
            continue
        if candidate == wanted:
            how = "场馆名匹配"
        elif (
            len(candidate) >= 4
            and len(candidate) >= 0.4 * len(wanted)
            and wanted.endswith(candidate)
        ):
            how = f"场馆名后缀匹配（高德条目：{raw}）"
        else:
            continue
        lng, lat = (float(x) for x in poi["location"].split(","))
        if best is None or how == "场馆名匹配":
            best = (how, lng, lat)
        if how == "场馆名匹配":
            break
    if best is None:
        return None
    how, lng, lat = best
    return lng, lat, how


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument(
        "--targets",
        choices=("all", "venues", "hotels"),
        default="all",
        help="which records to place (hotels carry coordinates too, and the comparison "
        "table counts them per business district)",
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    key = load_key()
    if not key:
        print("No AMAP_WEBSERVICE_KEY. Set it in the environment or frontend/.env.local.")
        return 2
    if not args.db.exists():
        print(f"missing database: {args.db}")
        return 1

    snap = snapshot(args.db)
    usage: dict[str, int] = {}
    for event in snap["events"]:
        venue_id = event.get("venueId")
        if venue_id:
            usage[venue_id] = usage.get(venue_id, 0) + 1

    # Hotels are placed by the same rule as venues, so a hotel and a venue that share a
    # business district end up in the same row and the comparison table can count them.
    targets: list[tuple[dict, bool]] = []
    if args.targets in ("all", "venues"):
        targets += [
            (venue, False) for venue in snap["venues"] if usage.get(venue["id"])
        ]
    if args.targets in ("all", "hotels"):
        targets += [(hotel, True) for hotel in snap["hotels"]]

    client = httpx.Client(timeout=20)
    resolved: dict[str, tuple[str, str, str]] = {}  # id -> (district, provenance, kind)
    hotels_resolved: dict[str, tuple[str, str, str]] = {}
    try:
        for record, is_hotel in targets:
            venue_id = record["id"]
            label = "酒店" if is_hotel else "场馆"
            coordinates = record.get("coordinates")
            lng = lat = None
            if coordinates and coordinates.get("lng") is not None:
                lng, lat = coordinates["lng"], coordinates["lat"]
                provenance = "已核验坐标逆地理编码"
            elif is_hotel:
                # A hotel is only placed from its own verified position; guessing a hotel's
                # location from its name would put it in the wrong district silently.
                continue
            else:
                # No coordinate stored: locate the venue by name purely to place it in the
                # right district. This does NOT write a coordinate.
                located = locate_missing(client, key, record.get("name") or "")
                if not located:
                    continue
                lng, lat, how = located
                provenance = f"{how}后逆地理编码"
            response = client.get(
                REGO_URL,
                params={
                    "key": key,
                    "location": f"{lng},{lat}",
                    "extensions": "base",
                    "radius": 1000,
                },
            )
            document = response.json()
            if document.get("status") != "1":
                print(f"  ! [{label}] {record['name']}: {document.get('info')}")
                time.sleep(0.4)
                continue
            component = (document.get("regeocode") or {}).get("addressComponent") or {}
            # Prefer the commercial district a local would name; fall back to the sub-district.
            areas = component.get("businessAreas") or []
            if isinstance(areas, dict):
                areas = [areas]
            named = next((a for a in areas if isinstance(a, dict) and a.get("name")), None)
            if named:
                name, kind = str(named["name"]), "business_area"
            else:
                name, kind = component.get("township"), "subdistrict"
                if isinstance(name, list):
                    name = "".join(name)
            if not name:
                print(f"  ! [{label}] {record['name']}: no business area or sub-district returned")
                time.sleep(0.4)
                continue
            (hotels_resolved if is_hotel else resolved)[venue_id] = (name, provenance, kind)
            kind_label = "商圈" if kind == "business_area" else "街道"
            print(f"  [{label}] {str(record['name'])[:24]:24s} -> {name}（{kind_label}）")
            time.sleep(0.4)
    finally:
        client.close()

    all_resolved = {**resolved, **hotels_resolved}
    names = sorted({name for name, _p, _k in all_resolved.values()})
    kinds = {name: kind for name, _p, kind in all_resolved.values()}
    print()
    print(f"venues reverse-geocoded: {len(resolved)}")
    print(f"hotels reverse-geocoded: {len(hotels_resolved)}")
    print(f"districts found        : {len(names)} -> {', '.join(names)}")

    assigned = sum(usage[vid] for vid in resolved if vid in usage)
    total = len(snap["events"])
    print(f"events assignable      : {assigned} / {total}")
    print(f"events unassigned      : {total - assigned} (no verified venue coordinate)")

    if not args.apply:
        print("\nDRY RUN: pass --apply to write districts and assign events")
        return 0

    with connect(args.db) as con:
        for name in names:
            payload = {
                "id": district_id(name),
                "name": name,
                "demo": False,
                "kind": kinds.get(name, "subdistrict"),
                "description": (
                    "高德逆地理编码返回的商圈"
                    if kinds.get(name) == "business_area"
                    else "高德逆地理编码返回的街道"
                ),
            }
            con.execute(
                "INSERT OR REPLACE INTO districts(id,payload) VALUES(?,?)",
                (payload["id"], json.dumps(payload, ensure_ascii=False, sort_keys=True)),
            )
        unassigned = {
            "id": UNASSIGNED,
            "name": "未归入商圈",
            "demo": False,
            "description": "场馆名称无法精确匹配到高德地点，暂未归入任何行政区",
        }
        con.execute(
            "INSERT OR REPLACE INTO districts(id,payload) VALUES(?,?)",
            (
                unassigned["id"],
                json.dumps(unassigned, ensure_ascii=False, sort_keys=True),
            ),
        )

        moved = 0
        for event in con.execute("SELECT id, payload FROM events").fetchall():
            payload = json.loads(event["payload"])
            venue_id = payload.get("venueId")
            # A hotel-only run must not rewrite the district of every unplaced venue's events.
            if venue_id not in resolved and args.targets == "hotels":
                continue
            target = (
                district_id(resolved[venue_id][0])
                if venue_id in resolved
                else UNASSIGNED
            )
            if payload.get("districtId") == target:
                continue
            payload["districtId"] = target
            con.execute(
                "UPDATE events SET district=?, payload=? WHERE id=?",
                (
                    target,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    event["id"],
                ),
            )
            moved += 1

        placed_hotels = 0
        for hotel in con.execute("SELECT id, payload FROM hotels").fetchall():
            payload = json.loads(hotel["payload"])
            entry = hotels_resolved.get(hotel["id"])
            if entry is None:
                continue
            target = district_id(entry[0])
            if payload.get("districtId") == target:
                continue
            payload["districtId"] = target
            con.execute(
                "UPDATE hotels SET payload=? WHERE id=?",
                (json.dumps(payload, ensure_ascii=False, sort_keys=True), hotel["id"]),
            )
            placed_hotels += 1
    print(
        f"\nAPPLIED: {len(names) + 1} districts written, {moved} events assigned, "
        f"{placed_hotels} hotels placed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
