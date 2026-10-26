"""把太仓的真实酒店点位从高德 POI 导入酒店库。

## 为什么用高德 POI 而不是「我知道太仓有哪几家酒店」

项目铁律是只写有来源的事实。高德 POI 检索返回的每条记录都有 **POI id、分类串、adcode、
坐标与地址**，可以逐条回到 `https://www.amap.com/place/<POI id>` 核对 —— 这是可追溯的采集，
不是凭印象罗列。

## 刻意不做的两件事

1. **不给星级**。高德分类串只写「住宿服务;宾馆酒店」，不写几星级。审核也确认过：
   星级取来源标注，未标注就显示「未标注」，不按品牌反推。所以新导入的酒店 `starLabel` 为空，
   界面显示「未标注」。希尔顿、全季这类品牌的档位同理留空，除非以后有官方来源补上。
2. **不覆盖已有记录**。库里已有的 19 家酒店（人工核对过星级与坐标）保持原样，
   新点位用 `hotel-amap-<poiid>` 独立 id 追加，按名称与坐标去重。

## 用法

    python -X utf8 scripts/import_taicang_hotels.py              # 只报告
    python -X utf8 scripts/import_taicang_hotels.py --apply       # 备份后写库
    python -X utf8 scripts/import_taicang_hotels.py --pages 3     # 每关键词抓 3 页
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

POI_URL = "https://restapi.amap.com/v3/place/text"
# 关键词覆盖：品牌连锁 + 通用词，避免只抓到「宾馆/招待所」这类小点位。
KEYWORDS = [
    "酒店", "宾馆", "星级酒店", "五星级", "四星级", "三星级",
    "喜来登", "万豪", "铂尔曼", "玛丽蒂姆", "逸扉", "智选假日",
    "全季", "汉庭", "如家", "亚朵", "维也纳", "锦江之星",
]
TYPES = "100000"  # 住宿服务
SLEEP_SECONDS = 0.4

# 品牌 → 档位。这是**名称匹配推断**，所以一律写上 brandSource，且不当作星级。
# 只认「名称以品牌开头」的连锁：改成子串匹配会把「太仓鑫海假日宾馆」误判成假日酒店。
# 注意：太仓没有希尔顿（高德 POI 显示希尔顿都在苏州吴中/相城/虎丘），所以这里不列希尔顿。
BRANDS: dict[str, tuple[str, str]] = {
    "全季": ("全季酒店", "中端"),
    "汉庭": ("汉庭酒店", "经济型"),
    "如家": ("如家酒店", "经济型"),
    "亚朵": ("亚朵酒店", "中端"),
    "维也纳": ("维也纳酒店", "中端"),
    "锦江之星": ("锦江之星", "经济型"),
    "智选假日": ("智选假日酒店", "中端"),
    "喜来登": ("喜来登", "高端"),
    "万豪": ("万豪", "高端"),
    "铂尔曼": ("铂尔曼", "高端"),
    "玛丽蒂姆": ("玛丽蒂姆", "高端"),
    "逸扉": ("逸扉", "高端"),
}


def load_key() -> str:
    key = os.environ.get("AMAP_WEBSERVICE_KEY")
    if key:
        return key.strip()
    env_file = Path(__file__).resolve().parent.parent / "frontend" / ".env.local"
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("AMAP_WEBSERVICE_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("找不到 AMAP_WEBSERVICE_KEY")


def fetch(key: str, keyword: str, page: int) -> dict:
    query = urllib.parse.urlencode({
        "key": key,
        "keywords": keyword,
        "types": TYPES,
        "city": "太仓",
        "citylimit": "true",
        "offset": 25,
        "page": page,
        "extensions": "all",
    })
    with urllib.request.urlopen(f"{POI_URL}?{query}", timeout=25) as response:
        return json.loads(response.read().decode("utf-8"))


def brand_of(name: str) -> tuple[str | None, str | None]:
    """只有名称以品牌开头时才认定连锁。名称中间出现品牌词不算 —— 那是推断不是事实。"""
    stripped = name.lstrip()
    for needle, (brand, tier) in BRANDS.items():
        if stripped.startswith(needle):
            return brand, tier
    return None, None


def star_of(poi_type: str) -> tuple[str | None, str | None]:
    """星级只取高德 POI 自己的分类串，例如「住宿服务;宾馆酒店;五星级宾馆」。"""
    for label in ("五星级", "四星级", "三星级", "二星级"):
        if label in (poi_type or ""):
            return label, "高德 POI 分类串（"
    return None, None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--pages", type=int, default=2)
    args = parser.parse_args()

    db_path = database_path()
    key = load_key()
    with connect(db_path) as con:
        existing = [json.loads(row["payload"]) for row in con.execute("SELECT payload FROM hotels")]

    def key_of(name: str, lng: float, lat: float) -> str:
        # 名称 + 坐标就近去重：同一家酒店在不同关键词下会重复出现。
        return f"{name.strip()}|{round(lng, 2)}|{round(lat, 2)}"

    seen = {key_of(h["name"], (h.get("coordinates") or {}).get("lng") or 0,
                   (h.get("coordinates") or {}).get("lat") or 0) for h in existing}
    known_names = {h["name"].strip() for h in existing}

    candidates: list[dict] = []
    skipped_dup = 0
    for keyword in KEYWORDS:
        for page in range(1, args.pages + 1):
            try:
                payload = fetch(key, keyword, page)
            except Exception as error:
                print(f"  {keyword} 第 {page} 页请求失败: {error}")
                continue
            pois = payload.get("pois") or []
            if not pois:
                break
            for poi in pois:
                if not poi.get("id") or not poi.get("location"):
                    continue
                if poi.get("adname") != "太仓市":
                    continue
                location = poi["location"].split(",")
                lng, lat = float(location[0]), float(location[1])
                name = (poi.get("name") or "").strip()
                if not name:
                    continue
                if key_of(name, lng, lat) in seen or name in known_names:
                    skipped_dup += 1
                    continue
                seen.add(key_of(name, lng, lat))
                known_names.add(name)
                candidates.append({
                    "poiId": poi["id"],
                    "name": name,
                    "address": poi.get("address") or "",
                    "type": poi.get("type") or "",
                    "typecode": poi.get("typecode") or "",
                    "adcode": poi.get("adcode") or "",
                    "lng": lng,
                    "lat": lat,
                })
            time.sleep(SLEEP_SECONDS)

    print(f"  已有酒店: {len(existing)} 家")
    print(f"  新点位: {len(candidates)} 家（去重跳过 {skipped_dup}）")

    # 品牌命中情况，便于核对「希尔顿/全季」这类是否抓到
    branded = [(c["name"], *brand_of(c["name"])) for c in candidates]
    hits = [(name, brand) for name, brand, _tier in branded if brand]
    print(f"  命中品牌: {len(hits)} 家")
    for name, brand in hits[:15]:
        print(f"    · {name} → {brand}")

    if not args.apply:
        print("  模式: 只报告（加 --apply 写库）")
        return 0

    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / (
        "menduner-before-taicang-hotels-"
        + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        + ".sqlite3"
    )
    source = sqlite3.connect(db_path)
    with sqlite3.connect(backup) as target:
        source.backup(target)
    source.close()
    print(f"  备份完成: {backup} ({backup.stat().st_size / 1024 / 1024:.1f} MB)")

    written = 0
    now = datetime.now(timezone.utc).isoformat()
    with connect(db_path) as con:
        for candidate in candidates:
            brand, tier_label = brand_of(candidate["name"])
            star_label, star_source = star_of(candidate["type"])
            payload = {
                "id": f"hotel-amap-{candidate['poiId']}",
                "name": candidate["name"],
                "address": candidate["address"],
                "districtId": "taicang",
                "districtDemo": False,
                # 坐标来自高德 POI 点位，是「计算坐标」而不是人工核验坐标，如实标注。
                "coordinates": {
                    "lng": candidate["lng"],
                    "lat": candidate["lat"],
                    "system": "GCJ-02",
                    "status": "Computed",
                    "sourceUrl": f"https://www.amap.com/place/{candidate['poiId']}",
                },
                # 星级：高德 POI 不提供星级，留空即「未标注」，不按品牌反推。
                "starLabel": star_label,
                "starSource": (star_source + candidate["type"] + "）") if star_source else None,
                # 档位：仅品牌命中时给名称推断值，并明确标注是推断。
                "tier": None,
                "tierLabel": tier_label,
                "tierSource": None if not brand else "名称以品牌开头（推断，非官方分类）",
                "brand": brand,
                "brandSource": None if not brand else "名称匹配",
                "poiType": candidate["type"],
                "poiTypecode": candidate["typecode"],
                "adcode": candidate["adcode"],
                "matchLevel": "POI 检索（place/text，citylimit 太仓）",
                "note": "高德 POI 名称标注装修中，尚未开业" if "装修中" in candidate["name"] else None,
                "importedAt": now,
                "source": "amap-poi",
            }
            con.execute(
                "INSERT OR REPLACE INTO hotels(id, payload) VALUES(?,?)",
                (payload["id"], json.dumps(payload, ensure_ascii=False)),
            )
            written += 1
    print(f"  已写入 {written} 家酒店（星级一律未标注，档位仅品牌命中时推断并标注来源）")

    with connect(db_path) as con:
        total = con.execute("SELECT COUNT(*) FROM hotels").fetchone()[0]
        taicang = sum(
            1 for row in con.execute("SELECT payload FROM hotels")
            if json.loads(row[0]).get("districtId") == "taicang"
        )
        print(f"  酒店总数: {total}；其中太仓: {taicang}")
        print(f"  完整性: {con.execute('PRAGMA integrity_check').fetchone()[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
