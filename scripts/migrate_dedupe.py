"""去重迁移：加 canonical_id 列、回填、报告；并附回滚方法。

    python -X utf8 scripts/migrate_dedupe.py            # 只报告（不写库）
    python -X utf8 scripts/migrate_dedupe.py --apply    # 备份 + 加列 + 回填

回滚：
    1. 恢复备份（脚本会在 --apply 时先备份到 data/backups/）；
    2. 或只清空派生字段：UPDATE events SET canonical_id = NULL;
       （canonical_id 是派生数据，清空后业务按「每条记录就是一条活动」工作，不丢任何原始记录）
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import dedupe
from backend.database import connect, database_path


def has_column(db_path: Path, table: str, column: str) -> bool:
    with connect(db_path) as con:
        return any(row[1] == column for row in con.execute(f"PRAGMA table_info({table})"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    db_path = database_path()
    print(f"  数据库: {db_path}")

    result = dedupe.summary(db_path)
    print(f"  事件记录        {result['events']}")
    print(f"  可合并簇        {result['clusters']}")
    print(f"  归并成员        {result['mergedMembers']}")
    print(f"  去重后身份      {result['remainingIdentities']}")
    print(f"  待人工确认候选  {result['candidates']}")
    for item in result["candidateDetail"][:5]:
        print(f"    · {item['aName'][:26]} × {item['bName'][:26]} —— {item['reason']}")
    if len(result["clusterDetail"]) > 0:
        print("  合并示例：")
        for cluster in result["clusterDetail"][:3]:
            print(f"    {cluster['canonical']} ← {len(cluster['members'])} 条")

    if not args.apply:
        print("  模式: 只报告（加 --apply 执行迁移与回填）")
        return 0

    # 备份：迁移前必须可回退。
    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup = backup_dir / f"menduner-before-dedupe-{stamp}.sqlite3"
    source = sqlite3.connect(db_path)
    with sqlite3.connect(backup) as target:
        source.backup(target)
    source.close()
    print(f"  备份完成: {backup}  ({backup.stat().st_size / 1024 / 1024:.1f} MB)")

    if not has_column(db_path, "events", "canonical_id"):
        with connect(db_path) as con:
            con.execute("ALTER TABLE events ADD COLUMN canonical_id TEXT")
            con.execute("CREATE INDEX IF NOT EXISTS idx_events_canonical ON events(canonical_id)")
        print("  已添加 events.canonical_id 列与索引")

    events, venues = dedupe.load_events(db_path)
    clusters, _ = dedupe.build_clusters(events, venues)
    merged = dedupe.apply(db_path, clusters)
    print(f"  已回填：{merged} 条记录归并到 {len(clusters)} 个规范活动")

    with connect(db_path) as con:
        print(f"  完整性: {con.execute('PRAGMA integrity_check').fetchone()[0]}")
        print(f"  外键问题: {len(con.execute('PRAGMA foreign_key_check').fetchall())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
