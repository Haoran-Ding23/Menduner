"""用场馆坐标的逆地理编码，把没有地区的活动归属到行政区。

## 为什么用逆地理编码，而不是按名称猜

活动本身没有坐标，但 447 条关联到了场馆，其中 429 条所在场馆有已核验坐标。坐标是可以问
地图服务「这个点属于哪个行政区」的——AMap 的 regeo 会返回 adname（例如「吴中区」「太仓市」）。
这是来源给出的答案，不是从活动名称里猜「苏州」两个字。

## 规则

  * 只在返回的城市是苏州市时归属到苏州的区县；外市场馆（例如上海的音乐会）保持未归属，
    因为把它们塞进「吴中区」之类的分类是错的；
  * 苏州工业园区在行政上属吴中区，按行政区归属并在 payload 里保留原始 adname；
  * 每条记录保留 adname、adcode、formatted_address 与来源，便于复核。

## 用法

    python -X utf8 scripts/assign_districts_by_regeo.py            # 只报告
    python -X utf8 scripts/assign_districts_by_regeo.py --apply    # 写入
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database import connect, database_path

ROOT = Path(__file__).resolve().parent.parent
DB = Path(os.environ.get("MENDUNER_DB_PATH", ROOT / "data" / "menduner.sqlite3"))

ADNAME_TO_SLUG = {
    "太仓市": "taicang",
    "昆山市": "kunshan",
    "常熟市": "changshu",
    "张家港市": "zhangjiagang",
    "姑苏区": "gusu",
    "虎丘区": "huqiu",
    "吴中区": "wuzhong",
    "相城区": "xiangcheng",
    "吴江区": "wujiang",
    # 苏州工业园区是功能区，行政上属吴中区。
    "工业园区": "wuzhong",
    "苏州工业园区": "wuzhong",
}
SUZHOU_CITIES = {"苏州市", "苏州"}


def amap_key() -> str | None:
    """The Web-service key, never passed on the command line.

    Reading it from an env var or a file keeps it out of shell history and out of process
    listings, which matters because this script runs on a shared server.
    """
    key = os.environ.get("AMAP_WEBSERVICE_KEY")
    if key:
        return key.strip()
    for candidate in (
        Path(os.environ.get("MENDUNER_ENV_FILE", "")),
        ROOT / "frontend" / ".env.local",
    ):
        if not candidate or not str(candidate) or not candidate.exists():
            continue
        lines = candidate.read_text(encoding="utf-8").splitlines()
        # The Web-service key must win: .env.local lists VITE_AMAP_KEY first, and that browser
        # key is rejected by /v3/geocode/regeo, which fails silently as "no coordinate".
        for name in ("AMAP_WEBSERVICE_KEY", "VITE_AMAP_KEY"):
            for line in lines:
                if line.startswith(name + "="):
                    return line.split("=", 1)[1].strip().strip('"')
    return None


def regeo(key: str, lng: float, lat: float, attempts: int = 3) -> dict | None:
    query = urllib.parse.urlencode({
        "key": key,
        "location": f"{lng:.6f},{lat:.6f}",
        "extensions": "base",
        "output": "JSON",
    })
    url = f"https://restapi.amap.com/v3/geocode/regeo?{query}"
    payload = {}
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception:
            payload = {}
        if payload.get("status") == "1":
            break
        # A personal key is rate-limited; back off instead of dropping the venue.
        time.sleep(1.2 * (attempt + 1))
    if payload.get("status") != "1":
        return None
    component = (payload.get("regeocode") or {}).get("addressComponent") or {}
    return {
        "adname": component.get("adname") or component.get("district"),
        "city": component.get("city") or component.get("province"),
        "adcode": component.get("adcode"),
        "address": (payload.get("regeocode") or {}).get("formatted_address"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    key = amap_key()
    if not key:
        print("  缺少 AMAP_WEBSERVICE_KEY（环境变量或 frontend/.env.local）")
        return 2

    stamp = datetime.now(timezone.utc).isoformat()
    with connect(DB) as con:
        venues = {row["id"]: json.loads(row["payload"])
                  for row in con.execute("SELECT id, payload FROM venues")}
        pending = [dict(row) for row in con.execute(
            "SELECT id, venue, payload FROM events WHERE district IS NULL"
        )]

        # 同一个场馆只问一次地图服务。
        targets: dict[str, list[dict]] = {}
        for event in pending:
            venue = venues.get(event["venue"] or "")
            coords = (venue or {}).get("coordinates") or {}
            if coords.get("lng") is None:
                continue
            targets.setdefault(event["venue"], []).append(event)

        print(f"  待归属事件 {len(pending)} 条，涉及场馆 {len(targets)} 个")

        assigned = 0
        outside = 0
        unknown = 0
        distribution: Counter[str] = Counter()

        for index, (venue_id, events) in enumerate(sorted(targets.items()), 1):
            coords = venues[venue_id]["coordinates"]
            try:
                info = regeo(key, coords["lng"], coords["lat"])
            except Exception as exc:
                print(f"    ! {venue_id} 逆地理编码失败: {type(exc).__name__}")
                unknown += len(events)
                continue
            if not info:
                unknown += len(events)
                continue

            slug = None
            if info["city"] in SUZHOU_CITIES or info["city"] is None:
                slug = ADNAME_TO_SLUG.get(info["adname"] or "")
            if slug is None:
                outside += len(events)
                if info["city"] not in SUZHOU_CITIES:
                    pass
                continue

            distribution[slug] += len(events)
            assigned += len(events)
            if args.apply and slug:
                for event in events:
                    payload = json.loads(event["payload"])
                    payload["districtRule"] = "场馆坐标逆地理编码（AMap regeo adname）"
                    payload["districtEvidence"] = {
                        "adname": info["adname"],
                        "adcode": info["adcode"],
                        "address": info["address"],
                        "source": "AMap Web 服务 API /v3/geocode/regeo",
                    }
                    payload["districtAssignedAt"] = stamp
                    con.execute(
                        "UPDATE events SET district=?, payload=? WHERE id=?",
                        (slug, json.dumps(payload, ensure_ascii=False), event["id"]),
                    )
            if index % 20 == 0:
                print(f"    …已处理场馆 {index}/{len(targets)}")
            time.sleep(0.36)

        total = con.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        still_null = con.execute(
            "SELECT COUNT(*) FROM events WHERE district IS NULL"
        ).fetchone()[0]
        print()
        print(f"  可归属 {assigned} 条，分布: {dict(distribution)}")
        print(f"  市外场馆不归属 {outside} 条；无法定位 {unknown} 条")
        print(f"  全库 {total} 条，仍无地区 {still_null} 条，"
              f"已归属 {total - still_null} 条（{(total - still_null) / total * 100:.1f}%）")
        print(f"  模式: {'写入' if args.apply else '只报告（加 --apply 写入）'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
