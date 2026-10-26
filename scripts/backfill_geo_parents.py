"""用高德逆地理给商圈/街道补父级行政区，并给所有行政区补原始行政编码。

审核（F05）要求：地理 API 的匹配级别、行政编码、街道与 businessAreas 分别保存，不要把行政
编码当成商业商圈的唯一身份。本地库现在这两样都没有，所以先补真实数据：

  * 商圈与街道的坐标来自高德，用坐标反查得到 adcode / adname / township / businessAreas；
  * 父级按 adname 匹配已存在的行政区（同名才认），匹配不到就保持未知，交给未归属分组；
  * 关键：**只新增字段，不改写已有字段**；adcode 存成 adminCode，与商圈自身 id 分开。

用法：
    python -X utf8 scripts/backfill_geo_parents.py            # 只报告
    python -X utf8 scripts/backfill_geo_parents.py --apply     # 备份后写库
    python -X utf8 scripts/backfill_geo_parents.py --limit 5   # 小批量试跑

回滚：写库前自动备份到 data/backups/；亦可按输出的 mapping JSON 逐条还原。
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
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database import connect, database_path

AMAP_URL = "https://restapi.amap.com/v3/geocode/regeo"
# 个人开发者 key 的 QPS 很低，逐条之间留出间隔，宁可慢也不要被限流后静默丢结果。
SLEEP_SECONDS = 0.45


def load_key() -> str:
    key = os.environ.get("AMAP_WEBSERVICE_KEY")
    if key:
        return key.strip()
    env_file = Path(__file__).resolve().parent.parent / "frontend" / ".env.local"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("AMAP_WEBSERVICE_KEY="):
                return line.split("=", 1)[1].strip()
    raise SystemExit("找不到 AMAP_WEBSERVICE_KEY（环境变量或 frontend/.env.local）")


def regeo(key: str, lng: float, lat: float) -> dict:
    query = urllib.parse.urlencode({
        "key": key,
        "location": f"{lng:.6f},{lat:.6f}",
        "extensions": "all",
        "radius": 1000,
        "output": "JSON",
    })
    with urllib.request.urlopen(f"{AMAP_URL}?{query}", timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--sleep", type=float, default=SLEEP_SECONDS)
    args = parser.parse_args()

    db_path = database_path()
    key = load_key()
    print(f"  数据库: {db_path}")

    with connect(db_path) as con:
        districts = {
            row["id"]: json.loads(row["payload"])
            for row in con.execute("SELECT id, payload FROM districts")
        }

    by_name: dict[str, str] = {}
    for identifier, district in districts.items():
        if district.get("kind") in ("city", "county_city", "district"):
            name = district.get("name")
            if name:
                by_name[name] = identifier

    # 行政区先补 adcode：它们的 payload 里有坐标的很少，所以按名字查行政区划？
    # 高德行政区划接口不在本脚本范围内 —— 行政区 adcode 用逆地理拿不到就留空，不编造。
    targets = [
        (identifier, district)
        for identifier, district in districts.items()
        if district.get("kind") in ("business_area", "subdistrict")
        and (district.get("coordinates") or {}).get("lng") is not None
        and (not district.get("parentId") or not district.get("adminCode"))
    ]
    if args.limit:
        targets = targets[: args.limit]
    print(f"  待补父级/编码的商圈与街道: {len(targets)}")

    mapping: list[dict] = []
    resolved = 0
    for index, (identifier, district) in enumerate(targets, 1):
        coords = district["coordinates"]
        try:
            payload = regeo(key, coords["lng"], coords["lat"])
        except Exception as error:  # 网络或配额问题：记录失败原因，继续下一条
            mapping.append({"id": identifier, "ok": False, "error": str(error)[:120]})
            print(f"    [{index}/{len(targets)}] {district.get('name')}: 请求失败 {error}")
            time.sleep(args.sleep)
            continue

        regeocode = payload.get("regeocode") or {}
        component = regeocode.get("addressComponent") or {}
        adname = component.get("district") or component.get("city") or ""
        adcode = component.get("adcode") or ""
        township = component.get("township") or ""
        business_areas = [
            {"name": item.get("name"), "location": item.get("location")}
            for item in (regeocode.get("businessAreas") or [])
        ]
        parent = by_name.get(adname)
        entry = {
            "id": identifier,
            "name": district.get("name"),
            "ok": bool(payload.get("status") == "1"),
            "adname": adname,
            "adcode": adcode,
            "township": township,
            "businessAreas": business_areas[:3],
            "parentId": parent,
            "parentKnown": parent is not None,
        }
        mapping.append(entry)
        if parent:
            resolved += 1
        print(
            f"    [{index}/{len(targets)}] {district.get('name')}: adname={adname or '-'} "
            f"adcode={adcode or '-'} 父级={'已匹配 ' + adname if parent else '未知'}"
        )
        time.sleep(args.sleep)

    print(f"  父级可确定: {resolved}/{len(targets)}；其余保持未知（进未归属分组）")

    report = db_path.parent / "backups" / (
        "geo-parent-mapping-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + ".json"
    )
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  映射报告: {report}")

    if not args.apply:
        print("  模式: 只报告（加 --apply 写库）")
        return 0

    # 备份：payload 改写前必须可回退
    backup_dir = db_path.parent / "backups"
    backup = backup_dir / (
        "menduner-before-geo-backfill-"
        + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        + ".sqlite3"
    )
    source = sqlite3.connect(db_path)
    with sqlite3.connect(backup) as target:
        source.backup(target)
    source.close()
    print(f"  备份完成: {backup} ({backup.stat().st_size / 1024 / 1024:.1f} MB)")

    written = 0
    with connect(db_path) as con:
        for entry in mapping:
            if not entry.get("ok"):
                continue
            identifier = entry["id"]
            with connect(db_path) as inner:
                row = inner.execute("SELECT payload FROM districts WHERE id=?", (identifier,)).fetchone()
            payload = json.loads(row["payload"])
            # 只新增/补空，绝不覆盖已有值：已有的 parentId 与 adminCode 优先。
            if entry.get("parentId") and not payload.get("parentId"):
                payload["parentId"] = entry["parentId"]
                payload["parentSource"] = "高德逆地理 adname 同名匹配"
            if entry.get("adcode") and not payload.get("adminCode"):
                payload["adminCode"] = entry["adcode"]
                payload["adminCodeSource"] = "高德逆地理 regeocode.addressComponent.adcode"
            if entry.get("township") and not payload.get("township"):
                payload["township"] = entry["township"]
                payload["townshipSource"] = "高德逆地理 regeocode.addressComponent.township"
            if entry.get("businessAreas") and not payload.get("businessAreas"):
                payload["businessAreas"] = entry["businessAreas"]
                payload["businessAreasSource"] = "高德逆地理 regeocode.businessAreas"
            if not payload.get("matchLevel"):
                payload["matchLevel"] = "regeo·addressComponent"
            con.execute(
                "UPDATE districts SET payload=? WHERE id=?",
                (json.dumps(payload, ensure_ascii=False), identifier),
            )
            written += 1
    print(f"  已写入 {written} 条（只补空，不覆盖）")

    with connect(db_path) as con:
        print(f"  完整性: {con.execute('PRAGMA integrity_check').fetchone()[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
