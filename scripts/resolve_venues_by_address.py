"""Resolve venues that have no coordinates, searching by ADDRESS first.

The first version searched by name and demanded a near-identical name back, which produced
false failures on venues that are trivially findable:

  * 开明大戏院 was rejected because AMap calls it 开明大戏院(观前街店);
  * 苏州奥体中心体育场 was rejected because the first two results are the surrounding complex —
    the actual 体育场 is the second one and was never looked at;
  * 橙天嘉禾剧场 was rejected because the stored name is 橙天嘉禾剧场 and AMap prefixes the city.

Every one of those venues HAS a street address, and AMap matches addresses very well. So the
signals are used in the order that discriminates:

  ADDRESS  the POI's street address must agree — this identifies the building, and it is why a
           differently-worded name is fine.
  KIND     the POI's type must be somewhere events are held (剧场, 体育馆, 展馆…). This is what
           rejects the 停车场, 公司 and 影城 that sit at the same address.
  NAME     only a sanity check: a shared distinctive word, or a branch suffix.

All three must hold. Dry-run by default; pass --apply to write.
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
from crawler.addresses import lookup_address  # noqa: E402

DEFAULT_DB = Path("backend/data/menduner.sqlite3")
POI_ENDPOINT = "https://restapi.amap.com/v3/place/text"
PLACE_URL = "https://ditu.amap.com/place/"
SUZHOU = ("苏州市", "昆山市", "常熟市", "太仓市", "张家港市")

# Somewhere a person can hold an event.
VENUE_TYPES = (
    "剧场", "影剧院", "电影院", "音乐厅", "文化宫", "展览馆", "美术馆", "博物馆",
    "图书馆", "体育馆", "体育场", "运动场馆", "会展中心", "会议中心", "活动中心",
    "纪念馆", "科技馆", "艺术中心", "文化中心", "游乐场", "风景名胜", "公园广场",
)
# Definitely not the venue, even at the right address.
REJECT_TYPES = (
    "停车场", "公司企业", "餐饮", "购物", "住宿", "加油站", "公交", "地铁", "银行",
    # AMap marks facilities INSIDE a site this way: 天平山景区-龙门一线天 and 天池山-某某景点 are
    # 风景名胜相关, while the scenic area itself is 风景名胜. Sub-features are not the venue.
    "相关",
)

# Distinctive words that identify a place, used only as a sanity check on the name.
WORDS = (
    "奥体", "奥林匹克", "博览", "开明", "橙天嘉禾", "保利", "湾",
    "狮山", "金鸡湖", "澹台", "黎里", "周庄", "阳澄湖", "东山", "太湖", "观前",
    "元和", "桃花坞", "南门", "留园", "枫桥", "彩香", "玉山", "城南", "体育",
    "剧场", "剧院", "音乐厅", "博物馆", "美术馆", "文化宫", "展馆", "图书馆",
    "景区", "古镇", "美术馆",
)


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


def identity(value: str | None) -> str:
    if not value:
        return ""
    cleaned = "".join(ch for ch in value if not ch.isspace() and ch not in "·・/／-—()（）")
    for prefix in ("苏州市", "苏州"):
        if cleaned.startswith(prefix) and len(cleaned) > len(prefix) + 2:
            return cleaned[len(prefix) :]
    return cleaned


def address_key(value: str | None) -> str:
    """The discriminating part of an address: the road plus the building number.

    '苏州 姑苏区 苏州开明大戏院 观前街北局11号' and '观前街北局11号' both reduce to '观前街北局11号',
    while a different venue on the same road keeps a different number.
    """
    if not value:
        return ""
    text = identity(value)
    match = re.search(r"([\u4e00-\u9fff]{1,10}(?:路|街|巷|大道|弄)\d+号?)", text)
    if match:
        return match.group(1)
    # AMap sometimes returns only a house number ("11号") for a venue whose own name is stored as
    # an address line. That is a weak signal kept for comparison, but a match is never granted on
    # it alone — see the name evidence requirement in match().
    match = re.search(r"(\d+号)", text)
    return match.group(1) if match else ""


def type_ok(poi_type: str | None) -> bool:
    text = poi_type or ""
    if any(bad in text for bad in REJECT_TYPES):
        return False
    return any(good in text for good in VENUE_TYPES)


def evidence(venue_name: str, poi_name: str, addr_key: str, poi_addr: str) -> str | None:
    """Decide whether a POI is the venue, and on what grounds.

    Two independent kinds of evidence, either of which suffices, because a name alone produces
    false failures and an address alone produces false matches:

      "name"  one normalised name contains the other. 开明大戏院 is inside 开明大戏院(观前街店) and
              苏州吴文化博物馆 contains 吴文化博物馆. This is strong on its own, which matters because
              AMap often returns only a house number for the address.

      "name+address"  a shared identifying word AND a matching address that includes a road name.
              Orange 橙天嘉禾 plus 引黛街9号 identifies 苏州橙天嘉禾剧场.

    Deliberately NOT sufficient: a shared generic word alone ("艺术" paired 苏艺大珍珠魔术剧场 with an
    unrelated theatre in the same complex), and a bare house number alone (数 venues share 观枫街1号).

    Alias pairs cover abbreviations no string comparison can bridge: 奥体 is 奥林匹克体育.
    """
    ours, theirs = identity(venue_name), identity(poi_name)
    if not ours or not theirs:
        return None
    if ours in theirs or theirs in ours:
        return "name"
    aliases = (("奥体", "奥林匹克"),)
    for short, long in aliases:
        if (short in ours and long in theirs) or (long in ours and short in theirs):
            return "alias"
    # A shared word must be specific. "艺术" appears in 苏州文化艺术中心 and in 苏艺大珍珠魔术剧场 and
    # identifies neither, so a short shared word needs company while a long one stands alone.
    shared = [w for w in WORDS if w in ours and w in theirs]
    specific = len(shared) >= 2 or any(len(w) >= 4 for w in shared)
    if not specific:
        return None
    # A named road is required before an address counts, and the two addresses must agree.
    road_named = bool(re.search(r"(?:路|街|巷|大道|弄)\d+", addr_key))
    if not (road_named and poi_addr and (addr_key in poi_addr or poi_addr in addr_key)):
        return None
    # A shared word plus a matching address still allowed 天平山景区 to match 天平山景区-龙门一线天 — a
    # feature INSIDE the scenic area, not the area itself. When the address carries no road name
    # the only thing left to check is the name, so it has to be the same name.
    if not road_named:
        return None
    if ours == theirs:
        return "name"
    return "name+address"


def query_pois(client, key: str, query: str):
    """AMap POI candidates for one query: ``(pois, None)`` or ``(None, reason)``."""
    try:
        document = client.get(
            POI_ENDPOINT,
            params={
                "key": key,
                "keywords": query,
                "city": "苏州",
                "offset": 10,
                "page": 1,
                "extensions": "all",
            },
        ).json()
    except Exception as exc:  # noqa: BLE001 - the reason is reported, not raised
        return None, f"ERROR {type(exc).__name__}"
    if document.get("status") != "1":
        return None, f"AMAP {document.get('info')}"
    return document.get("pois") or [], None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--interval", type=float, default=1.1, help="seconds between queries")
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
        vid = event.get("venueId")
        if vid:
            usage[vid] = usage.get(vid, 0) + 1
    known = {v["id"]: v for v in snap["venues"]}
    pending = [
        known[vid]
        for vid, count in sorted(usage.items(), key=lambda kv: -kv[1])
        if count and vid in known and not known[vid].get("coordinates")
    ]
    if args.limit:
        pending = pending[: args.limit]

    print(f"database: {args.db}")
    print(f"venues an event references with no coordinates: {len(pending)}")
    print()

    client = httpx.Client(timeout=25)
    matched: list[tuple[dict, dict]] = []
    failed: list[dict] = []
    try:
        for index, venue in enumerate(pending, start=1):
            name = venue.get("name") or ""
            address = venue.get("address") or ""
            addr_key = address_key(address)
            # Address first when there is one — it is the discriminating signal. Name alone is
            # the weaker query and is what produced the false failures. When the full address
            # finds nothing, the same address reduced to its road and house number is tried
            # next: AMap indexes "松涛街1088号" better than the building detail behind it.
            queries = []
            if addr_key:
                queries.append(("address", f"{address} {name}".strip()))
                reduced = lookup_address(address)
                if reduced and reduced != address:
                    queries.append(("road+number", f"{reduced} {name}".strip()))
            if not queries:
                queries.append(("name", name))

            best = None
            failure = None
            for kind, query in queries:
                pois, failure = query_pois(client, key, query)
                if pois is None:
                    break
                for poi in pois:
                    if not poi.get("location") or not poi.get("id"):
                        continue
                    if not any(area in (poi.get("cityname") or "") for area in SUZHOU):
                        continue
                    if not type_ok(poi.get("type")):
                        continue
                    poi_addr = address_key(poi.get("address"))
                    grounds = evidence(name, poi.get("name") or "", addr_key, poi_addr)
                    if grounds is None:
                        continue
                    lng, lat = (float(x) for x in poi["location"].split(","))
                    best = (poi, lng, lat, grounds, kind, query)
                    break
                if best:
                    break
                time.sleep(args.interval)

            if best is None:
                print(f"  [{index:2d}] {name[:28]:28s} 无可靠匹配（未写入）"
                      + (f"  {failure}" if failure else ""))
                failed.append(venue)
            else:
                poi, lng, lat, grounds, kind, query = best
                print(
                    f"  [{index:2d}] {name[:28]:28s} MATCH({grounds}/{kind}) {lng:.6f},{lat:.6f}\n"
                    f"        -> {poi.get('name')}  [{str(poi.get('type'))[:34]}]\n"
                    f"        -> 地址 {address_key(poi.get('address')) or poi.get('address')}  "
                    f"id={poi.get('id')}\n"
                    f"        -> 查询 {query}"
                )
                matched.append(
                    (
                        venue,
                        {
                            "lng": lng,
                            "lat": lat,
                            "poi_id": poi.get("id"),
                            "poi_name": poi.get("name"),
                            "poi_address": poi.get("address"),
                        },
                    )
                )
            time.sleep(args.interval)
    finally:
        client.close()

    print()
    print(f"matched : {len(matched)}  (address + venue type + name hint all agree)")
    print(f"unmatched: {len(failed)}")

    if not args.apply:
        print("\nDRY RUN: pass --apply to write the matched coordinates")
        return 0

    with connect(args.db) as con:
        for venue, poi in matched:
            row = con.execute("SELECT payload FROM venues WHERE id=?", (venue["id"],)).fetchone()
            payload = json.loads(row["payload"])
            payload["coordinates"] = {
                "lng": poi["lng"],
                "lat": poi["lat"],
                "system": "GCJ-02",
                "status": "Verified",
                "sourceUrl": PLACE_URL + str(poi["poi_id"]),
            }
            con.execute(
                "UPDATE venues SET payload=? WHERE id=?",
                (json.dumps(payload, ensure_ascii=False, sort_keys=True), venue["id"]),
            )
    print(f"\nAPPLIED: {len(matched)} venues given verified coordinates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
