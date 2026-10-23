"""把苏州市星级饭店名录里的 4 家太仓星级酒店加进酒店库。

星级来自官方名录（已交叉验证的来源），坐标来自高德 place/text，两者都保留来源。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database import connect, database_path

ROOT = Path(__file__).resolve().parent.parent

HOTELS = [
    {"name": "太仓花园酒店", "star": 5},
    {"name": "太仓锦江国际大酒店", "star": 5},
    {"name": "太仓陆渡宾馆", "star": 4},
    {"name": "太仓市娄东宾馆", "star": 4},
]
STAR_NAME = "苏州市旅游咨询中心《苏州星级酒店名录》"
STAR_URL = "https://visitsz.wglj.suzhou.com.cn/news-detail.aspx?id=1662"


def amap_key() -> str | None:
    if os.environ.get("AMAP_WEBSERVICE_KEY"):
        return os.environ["AMAP_WEBSERVICE_KEY"].strip()
    path = Path(os.environ.get("MENDUNER_ENV_FILE", "") or ".")
    if path.is_file():
        lines = path.read_text(encoding="utf-8").splitlines()
        for name in ("AMAP_WEBSERVICE_KEY", "VITE_AMAP_KEY"):
            for line in lines:
                if line.startswith(name + "="):
                    return line.split("=", 1)[1].strip().strip('"')
    return None


def search(key: str, keyword: str) -> dict | None:
    query = urllib.parse.urlencode({
        "key": key, "keywords": keyword, "city": "太仓", "citylimit": "true",
        "offset": "5", "page": "1", "extensions": "base", "output": "JSON",
    })
    url = f"https://restapi.amap.com/v3/place/text?{query}"
    with urllib.request.urlopen(url, timeout=25) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("status") != "1":
        return None
    pois = payload.get("pois") or []
    key_core = keyword.replace("市", "")
    for poi in pois:
        if key_core in (poi.get("name") or "").replace("市", ""):
            return poi
    return pois[0] if pois else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    key = amap_key()
    if not key:
        print("缺少高德 Web 服务 Key")
        return 2

    stamp = datetime.now(timezone.utc).isoformat()
    with connect(database_path()) as con:
        existing = {json.loads(r["payload"]).get("name")
                    for r in con.execute("SELECT payload FROM hotels")}
        for item in HOTELS:
            name = item["name"]
            if name in existing:
                print(f"  {name}: 已存在，跳过")
                continue
            poi = search(key, name)
            if not poi:
                print(f"  {name}: 高德未找到")
                continue
            lng, lat = (poi.get("location") or ",").split(",")
            tier = "high" if item["star"] == 5 else "mid"
            tier_label = "高端" if item["star"] == 5 else "中端"
            star_label = f"{item['star']}星级"
            payload = {
                "id": "h-" + hashlib.sha256(name.encode()).hexdigest()[:16],
                "name": name,
                "address": poi.get("address"),
                "districtId": "taicang",
                "districtDemo": False,
                "coordinates": {
                    "lng": float(lng), "lat": float(lat), "system": "GCJ-02",
                    "status": "Verified",
                    "sourceUrl": f"https://www.amap.com/place/{poi.get('id')}",
                },
                "tier": tier,
                "tierLabel": tier_label,
                "tierSource": STAR_NAME,
                "tierEvidence": f"官方名录 {star_label}",
                "star": {
                    "level": item["star"], "label": star_label, "claimedStar": True,
                    "status": "Verified", "category": star_label,
                    "source": STAR_NAME, "sourceUrl": STAR_URL,
                    "evidence": f"官方名录 {star_label}", "rule": "官方名录星级",
                },
                "officialStar": {
                    "level": item["star"], "label": star_label, "name": name,
                    "address": poi.get("address"), "source": STAR_NAME,
                    "sourceUrl": STAR_URL, "publishedAt": "2024/4/7", "importedAt": stamp,
                },
            }
            print(f"  {name}: {poi.get('address')} ({lng},{lat}) → {star_label}")
            if args.apply:
                con.execute("INSERT INTO hotels(id, payload) VALUES(?,?)",
                            (payload["id"], json.dumps(payload, ensure_ascii=False)))
        if args.apply:
            total = con.execute("SELECT COUNT(*) FROM hotels").fetchone()[0]
            print(f"\n  酒店总数 {total}")
    print(f"  模式: {'写入' if args.apply else '只报告（加 --apply 写入）'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
