"""从高德分类标注中提取酒店星级，写成可筛选的结构化字段。

## 为什么不是直接给个星级

现在每家酒店只有「档位」（高端/中端/舒适），那是按品牌定位判断的。用户要的是按星级找酒店，
但**星级是国家评定，不是品牌定位**：洲际是高端品牌，但它在这个城市有没有挂牌五星，需要来源
说了才算。凭空把「高端」写成「五星」就是编造。

好在原始证据里已经有真东西：高德把这几家标成了「五星级宾馆」「四星级宾馆」「三星级宾馆」
「经济型连锁酒店」。这句话本身就是分类标注，可以原样保留成字段。

## 规则

  * 证据里出现「X星级宾馆」→ 该星级，状态 Verified，并在字段里留原文分类串；
  * 只有「经济型连锁酒店」→ 不声称星级，标签「经济型」，状态 Unstated；
  * 两者都没有 → 星级未知，状态 Unstated，不猜；
  * 与现有档位明显矛盾时（例如档位高端但标注三星），不改档位，只在报告里列出来。

## 用法

    python -X utf8 scripts/derive_hotel_stars.py            # 只报告
    python -X utf8 scripts/derive_hotel_stars.py --apply    # 写入 payload.star
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database import connect, database_path

STAR_WORDS = {
    "五星级": 5,
    "四星级": 4,
    "三星级": 3,
    "二星级": 2,
    "一星级": 1,
}
ECONOMY = "经济型"

# Tier to the star band it would normally sit in, used only to REPORT contradictions.
TIER_BANDS = {"high": {4, 5}, "mid": {3, 4}, "comfort": {2, 3}}


def parse(evidence: str) -> dict | None:
    """Return a star record from the AMap category text, or None when it states nothing."""
    if not evidence:
        return None
    for segment in evidence.split("|"):
        for word, level in STAR_WORDS.items():
            if word in segment:
                return {
                    "level": level,
                    "label": f"{level}星级",
                    "category": segment.strip(),
                    "claimedStar": True,
                }
        if ECONOMY in segment and "宾馆" in segment or ECONOMY in segment and "酒店" in segment:
            return {
                "level": None,
                "label": ECONOMY,
                "category": segment.strip(),
                "claimedStar": False,
            }
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="写入 payload.star")
    args = parser.parse_args()

    db = database_path()
    stamp = datetime.now(timezone.utc).isoformat()
    counts: dict[str, int] = {}
    conflicts: list[str] = []

    with connect(db) as con:
        rows = list(con.execute("SELECT id, payload FROM hotels"))
        for row in rows:
            payload = json.loads(row["payload"])
            star = parse(payload.get("tierEvidence", ""))
            tier = payload.get("tier")
            source_url = (payload.get("coordinates") or {}).get("sourceUrl")

            if star is None:
                record = {
                    "level": None,
                    "label": "未标注",
                    "claimedStar": False,
                    "status": "Unstated",
                    "source": "高德分类标注",
                    "sourceUrl": source_url,
                    "evidence": payload.get("tierEvidence", ""),
                    "rule": "高德分类未标注星级；不按品牌推断",
                    "derivedAt": stamp,
                }
            else:
                record = {
                    **star,
                    "status": "Verified" if star["claimedStar"] else "Unstated",
                    "source": "高德分类标注",
                    "sourceUrl": source_url,
                    "evidence": payload.get("tierEvidence", ""),
                    "rule": "取自高德分类串中的星级/经济型标注，原文保留在 category",
                    "derivedAt": stamp,
                }

            key = record["label"]
            counts[key] = counts.get(key, 0) + 1

            band = TIER_BANDS.get(tier or "", set())
            if record["claimedStar"] and band and record["level"] not in band:
                conflicts.append(
                    f"{payload.get('name')}: 档位 {tier} 但标注 {record['label']}"
                )

            if args.apply:
                payload["star"] = record
                con.execute(
                    "UPDATE hotels SET payload=? WHERE id=?",
                    (json.dumps(payload, ensure_ascii=False), row["id"]),
                )

    print(f"  模式: {'写入' if args.apply else '只报告'}")
    print(f"  酒店: {len(rows)} 家")
    print("  分布:")
    for label, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"    {label}: {count}")
    print(f"  档位与标注矛盾的: {len(conflicts)}")
    for line in conflicts:
        print(f"    ! {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
