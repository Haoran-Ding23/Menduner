"""把「太仓文化」来源的活动归属到太仓市。

## 为什么这是数据问题而不是抓取问题

太仓来源已经抓到 132 条活动，但 `events.district` 全是 NULL。地区筛选和地图都按 district 取数，
所以这 132 条在地图上「不存在」——太仓看起来活动很少，有一部分原因是**已经抓到的数据没有落位**。

## 归属依据

`government-taicang-culture` 是太仓市人民政府网站「政务服务 > 专题服务 > 文化教育 > 太仓文化」
栏目，只发布太仓市内的文化活动。因此该来源的记录属于太仓市，slug 为 `taicang`。

不是按名称猜的：名称里带「太仓」只是巧合（例如「铁军东进——新四军在常武大地」是在太仓场馆
办的常州主题展），判断依据是**发布主体**。

## 用法

    python -X utf8 scripts/assign_taicang_district.py            # 只报告
    python -X utf8 scripts/assign_taicang_district.py --apply    # 写入
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database import connect, database_path

SOURCE = "government-taicang-culture"
DISTRICT = "taicang"
DISTRICT_NAME = "太仓市"
RULE = "来源为太仓市人民政府网站「太仓文化」栏目，只发布太仓市内活动"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    stamp = datetime.now(timezone.utc).isoformat()
    with connect(database_path()) as con:
        rows = list(con.execute(
            "SELECT id, payload FROM events WHERE source=? AND district IS NULL", (SOURCE,)
        ))
        print(f"  待归属: {len(rows)} 条（来源 {SOURCE}）")

        years: dict[str, int] = {}
        future = 0
        today = datetime.now(timezone.utc).date().isoformat()
        for row in rows:
            payload = json.loads(row["payload"])
            start = payload.get("startDate") or ""
            years[start[:4]] = years.get(start[:4], 0) + 1
            if start >= today:
                future += 1
            if args.apply:
                payload["districtRule"] = RULE
                payload["districtAssignedAt"] = stamp
                con.execute(
                    "UPDATE events SET district=?, payload=? WHERE id=?",
                    (DISTRICT, json.dumps(payload, ensure_ascii=False), row["id"]),
                )

        if args.apply:
            total = con.execute(
                "SELECT COUNT(*) FROM events WHERE source=? AND district=?", (SOURCE, DISTRICT)
            ).fetchone()[0]
            print(f"  已归属 {DISTRICT_NAME}: {total} 条")
        print(f"  按年: {dict(sorted(years.items()))}")
        print(f"  今天({today})及以后: {future} 条")
        print(f"  模式: {'写入' if args.apply else '只报告（加 --apply 写入）'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
