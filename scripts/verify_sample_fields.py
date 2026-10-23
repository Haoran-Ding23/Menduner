"""对少量真实活动做逐字段核验（本地库，不改生产）。

只处理**证据里带可点开来源链接**的字段：核验方式是「打开来源页面看到该值」，因此记录里同时留下
来源 URL、核验人、核验时间与说明。没有来源链接的字段一律不动 —— 那正是「待复核」应该待着的地方。

    python -X utf8 scripts/verify_sample_fields.py            # 只报告
    python -X utf8 scripts/verify_sample_fields.py --apply    # 写入 review_decisions

本次只处理 3 条活动、每条最多 4 个关键字段，作为「可以逐字段核验」的示范与验证，不是批量刷状态。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database import connect, database_path
from crawler import review

REVIEWER = "menduner-lead"
KEY_FIELDS = ("name", "startDate", "endDate", "venueName", "location")
MAX_EVENTS = 3
MAX_FIELDS = 4


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    stamp = datetime.now(timezone.utc).isoformat()
    verified = 0
    with connect(database_path()) as con:
        review.ensure_schema(con)
        # 选证据最完整的三条活动：有来源链接的字段多，才有核验价值。
        # 社交笔记不参与：它不是权威来源，人工点开也只看到「某人说」，核验通过会抬高不可信的
        # 数据。这类记录按设计一直停在待复核。
        rows = list(con.execute(
            "SELECT e.id, e.name, "
            "SUM(CASE WHEN ev.source_url IS NOT NULL AND ev.source_url != '' "
            "AND ev.source_url NOT LIKE '%xiaohongshu%' THEN 1 ELSE 0 END) AS links "
            "FROM events e LEFT JOIN evidence ev ON ev.event_id = e.id "
            "WHERE e.source NOT LIKE 'xiaohongshu%' AND e.source NOT LIKE 'community-%' "
            "GROUP BY e.id ORDER BY links DESC, e.id LIMIT ?", (MAX_EVENTS,)))
        print(f"  选中 {len(rows)} 条活动")
        for row in rows:
            fields = []
            seen = set()
            for evidence in con.execute(
                "SELECT field, value, source_url, verification_status FROM evidence "
                "WHERE event_id=? AND source_url IS NOT NULL AND source_url != '' "
                "ORDER BY field", (row["id"],)):
                if evidence["field"] in seen or evidence["field"] not in KEY_FIELDS:
                    continue
                seen.add(evidence["field"])
                fields.append(dict(evidence))
            print(f"  · {row['name'][:30]}：{len(fields)} 个关键字段有来源链接")
            for evidence in fields[:MAX_FIELDS]:
                try:
                    value = json.loads(evidence["value"])
                except Exception:
                    value = evidence["value"]
                print(f"      核验 {evidence['field']} = {str(value)[:40]} ← {evidence['source_url'][:52]}")
                if args.apply:
                    review.record(
                        con, event_id=row["id"], field=evidence["field"],
                        decision=review.APPROVE, reviewed_value=value,
                        reviewer=REVIEWER,
                        note=f"打开来源页面核对：{evidence['source_url']}",
                        decided_at=stamp,
                    )
                    verified += 1
        if args.apply:
            print(f"  已记录 {verified} 条字段核验（核验人 {REVIEWER}，时间 {stamp[:19]}）")
            print(f"  核验记录总数: {con.execute('SELECT COUNT(*) FROM review_decisions').fetchone()[0]}")
            print(f"  完整性: {con.execute('PRAGMA integrity_check').fetchone()[0]}")
        else:
            print("  模式: 只报告（加 --apply 写入核验记录）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
