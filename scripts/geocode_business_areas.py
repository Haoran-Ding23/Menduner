"""给商圈补「中心点 + 来源 + 匹配级别」，不伪造边界。

为什么不用多边形：高德不给商圈边界，任何"画出来的圈"都是我们编的。所以只用
「中心点 + 半径」表示估算范围，并且把来源、匹配到的 POI 名、行政区一致性都记下来，
页面上一律写「商圈中心点周边活动（估算范围）」，不写「商圈内活动」。

判定规则（GPT Round 14 的要求）：
  * 坐标系统一 GCJ-02；
  * 商圈名与高德返回的 adname 必须与 parentId 对应的行政区一致，否则标 unverified；
  * 一个商圈若解析出多个候选 POI（模糊），只取第一条但在 note 里写明候选数；
  * 解析不到就留空，不猜。

用法：
  python scripts/geocode_business_areas.py --dry-run
  python scripts/geocode_business_areas.py --apply      # 只补空，不覆盖已有中心点
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database import connect, database_path  # noqa: E402

KEY = os.environ.get("AMAP_WEBSERVICE_KEY", "").strip()
BASE = "https://restapi.amap.com/v3/place/text"
DEFAULT_RADIUS = 1200  # 实验半径；页面标注为估算范围


def amap_search(keyword: str, city: str) -> dict:
    query = urllib.parse.urlencode({
        "key": KEY, "keywords": keyword, "city": city, "citylimit": "true",
        "offset": "5", "page": "1", "extensions": "base",
    })
    with urllib.request.urlopen(f"{BASE}?{query}", timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def payloads(path: Path, table: str) -> list[dict]:
    with connect(path) as con:
        return [json.loads(row[0]) for row in con.execute(f"SELECT payload FROM {table}")]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--radius", type=int, default=DEFAULT_RADIUS)
    args = parser.parse_args()
    if not args.apply and not args.dry_run:
        args.dry_run = True
    if args.apply and not KEY:
        print("缺少 AMAP_WEBSERVICE_KEY")
        return 2

    path = database_path()
    districts = payloads(path, "districts")
    by_id = {d["id"]: d for d in districts}
    areas = [d for d in districts if d.get("kind") == "business_area"]
    print(f"  商圈 {len(areas)} 个，库 {path}")

    if args.apply:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        backup = path.parent / "backups" / f"menduner-before-area-center-{stamp}.sqlite3"
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup)
        print(f"  备份: {backup} ({backup.stat().st_size // 1048576} MB)")

    results, written, skipped = [], 0, 0
    for area in areas:
        name = area.get("name") or ""
        parent = by_id.get(area.get("parentId") or "") or {}
        parent_name = parent.get("name") or ""
        if (area.get("center") or {}).get("lng"):
            skipped += 1
            results.append({"area": name, "status": "已有中心点，跳过"})
            continue
        if not KEY:
            results.append({"area": name, "status": "dry-run 未请求（无 key）"})
            continue

        record = {"area": name, "parent": parent_name}
        try:
            data = amap_search(name, parent_name.replace("市", "") or "苏州")
        except Exception as error:  # 网络失败要留痕，不能静默
            record.update(status=f"请求失败: {error}")
            results.append(record)
            continue
        time.sleep(0.45)  # 个人 key 约 3 QPS

        pois = data.get("pois") or []
        if not pois:
            record.update(status="未解析到 POI，保持未知")
            results.append(record)
            continue

        best = pois[0]
        location = (best.get("location") or "").split(",")
        if len(location) != 2:
            record.update(status="POI 无坐标，保持未知")
            results.append(record)
            continue
        lng, lat = float(location[0]), float(location[1])
        adname = best.get("adname") or ""
        consistent = bool(parent_name) and (parent_name.replace("市", "") in adname or adname in parent_name)
        center = {
            "lng": lng, "lat": lat, "system": "GCJ-02",
            "source": "amap-place-text", "sourceUrl": f"https://uri.amap.com/marker?position={lng},{lat}",
            "matchedName": best.get("name"), "adname": adname,
            "matchedAt": datetime.now(timezone.utc).isoformat(),
            "radiusMeters": args.radius,
            "matchLevel": "verified" if consistent else "unverified",
            "candidateCount": len(pois),
            "note": "" if consistent else f"返回行政区 {adname} 与父级 {parent_name} 不一致",
        }
        payload = dict(area)
        payload["center"] = center
        # 同时写入 businessAreas 便于既有页面/导出复用
        payload.setdefault("businessAreas", [])

        record.update({"status": "ok", "adname": adname, "level": center["matchLevel"],
                       "poi": best.get("name"), "candidates": len(pois)})
        results.append(record)

        if args.apply:
            with connect(path) as con:
                con.execute("UPDATE districts SET payload=? WHERE id=?",
                            (json.dumps(payload, ensure_ascii=False), area["id"]))
            written += 1

    for row in results:
        print(f"  - {row.get('area')}: {row.get('status')}"
              + (f" | POI={row.get('poi')} | {row.get('adname')} | {row.get('level')}"
                 if row.get("status") == "ok" else ""))
    ok = sum(1 for r in results if r.get("status") == "ok")
    verified = sum(1 for r in results if r.get("level") == "verified")
    print(f"\n  解析成功 {ok}/{len(areas)}，其中行政区一致 verified {verified}；跳过（已有）{skipped}；本次写入 {written}")

    if args.apply:
        report = path.parent / "backups" / f"area-center-report-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.json"
        report.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  报告: {report}")
        with connect(path) as con:
            print("  完整性:", con.execute("PRAGMA integrity_check").fetchone()[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
