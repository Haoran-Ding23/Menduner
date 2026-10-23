"""把社交导入的活动归到它们实际所属的城市/区。

社交笔记只给场馆名，不给坐标；这批事件的 district 因此全是 NULL。归属依据是**场馆名在高德的
行政区**（place/text → adcode/adname），而不是从标题里认字。没有场馆时退回 AI 读出的
``payload.location``（例如「苏州」），并且只敢归到市级，不猜具体区。

    python -X utf8 scripts/assign_xhs_districts.py            # 只报告
    python -X utf8 scripts/assign_xhs_districts.py --apply    # 写入
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = Path(os.environ.get("XHS_DB", ROOT / "scratch.sqlite3"))

ADNAME_TO_SLUG = {
    "太仓市": "taicang", "昆山市": "kunshan", "常熟市": "changshu", "张家港市": "zhangjiagang",
    "姑苏区": "gusu", "虎丘区": "huqiu", "吴中区": "wuzhong", "相城区": "xiangcheng",
    "吴江区": "wujiang", "工业园区": "wuzhong", "苏州工业园区": "wuzhong",
}


def amap_key() -> str | None:
    """Read the key from the local env file; never from an argument, never printed."""
    if os.environ.get("AMAP_WEBSERVICE_KEY"):
        return os.environ["AMAP_WEBSERVICE_KEY"].strip()
    for candidate in (Path(os.environ.get("MENDUNER_ENV_FILE", "") or "."),
                      ROOT / "frontend" / ".env.local"):
        if not candidate.is_file():
            continue
        lines = candidate.read_text(encoding="utf-8").splitlines()
        for name in ("AMAP_WEBSERVICE_KEY", "VITE_AMAP_KEY"):
            for line in lines:
                if line.startswith(name + "="):
                    return line.split("=", 1)[1].strip().strip('"')
    return None


def lookup(key: str, name: str) -> dict | None:
    """Resolve a venue name to an administrative district, preferring Suzhou matches."""
    for city, citylimit in (("苏州", "true"), ("", "false")):
        query = {"key": key, "keywords": name, "offset": "5", "page": "1",
                 "extensions": "base", "output": "JSON"}
        if city:
            query["city"] = city
            query["citylimit"] = citylimit
        url = "https://restapi.amap.com/v3/place/text?" + urllib.parse.urlencode(query)
        try:
            with urllib.request.urlopen(url, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception:
            return None
        if payload.get("status") != "1":
            continue
        for poi in payload.get("pois") or []:
            adcode = str(poi.get("adcode") or "")
            # 32 = 江苏; 3205 = 苏州. Anything else is a different city.
            if city and not adcode.startswith("3205"):
                continue
            return {
                "poi": poi.get("name"),
                "adname": poi.get("adname") or "",
                "adcode": adcode,
                "city": "苏州" if adcode.startswith("3205") else adcode[:4],
                "location": poi.get("location"),
            }
        time.sleep(0.3)
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    key = amap_key()
    if not key:
        print("缺少高德 Web 服务 Key")
        return 2

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    venues = {r["id"]: json.loads(r["payload"]) for r in con.execute("SELECT id,payload FROM venues")}
    events = list(con.execute("SELECT id,name,startDate,venue,payload FROM events"))

    cache: dict[str, dict | None] = {}
    assigned = 0
    unresolved = []
    print(f"  事件 {len(events)} 条\n")
    for event in events:
        payload = json.loads(event["payload"])
        venue = venues.get(event["venue"] or "") or {}
        venue_name = venue.get("name") or payload.get("venueName")

        slug = None
        evidence = None
        if venue_name:
            if venue_name not in cache:
                cache[venue_name] = lookup(key, venue_name)
            info = cache[venue_name]
            if info:
                slug = ADNAME_TO_SLUG.get(info["adname"])
                evidence = f"高德 place/text：{info['poi']} → {info['adname']}（adcode {info['adcode']}）"
                if slug is None:
                    evidence += "（该 adname 不在苏州区县映射内）"
        if slug is None:
            # 没有场馆或场馆查不到时，退回 AI 读出的城市；只到市级，不猜区。
            location = (payload.get("location") or "").strip()
            if "太仓" in location:
                slug, evidence = "taicang", f"AI 读出的地点「{location}」，未定位到具体场馆"
            elif "苏州" in location:
                slug, evidence = "suzhou", f"AI 读出的地点「{location}」，只到市级"
            elif location:
                evidence = f"AI 读出的地点「{location}」不在苏州范围内"

        mark = "→" + (slug or "未确定")
        print(f"  {event['startDate']}  {event['name'][:26]:26s} 场馆={str(venue_name)[:22]:22s} {mark}")
        if slug:
            assigned += 1
            if args.apply:
                payload["districtId"] = slug
                payload["districtEvidence"] = evidence
                con.execute("UPDATE events SET district=?, payload=? WHERE id=?",
                            (slug, json.dumps(payload, ensure_ascii=False), event["id"]))
        else:
            unresolved.append((event["name"], evidence))

    if args.apply:
        con.commit()
    print(f"\n  可归属 {assigned} / {len(events)}")
    if unresolved:
        print("  未确定：")
        for name, reason in unresolved:
            print(f"    · {name} —— {reason}")
    print(f"  模式: {'写入' if args.apply else '只报告'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
