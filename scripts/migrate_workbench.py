"""工作台数据层迁移：建表 + 记录第一份快照。

    python -X utf8 scripts/migrate_workbench.py            # 只报告
    python -X utf8 scripts/migrate_workbench.py --apply    # 备份 + 建表 + 首次快照

回滚：
    这两张表都是**新增且不影响既有数据**的：删掉即可回到迁移前
        DROP TABLE IF EXISTS event_snapshots;
        DROP TABLE IF EXISTS event_followups;
    或恢复 data/backups/ 下的备份。
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import tracking
from backend.database import connect, database_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    db_path = database_path()
    print(f"  数据库: {db_path}")

    with connect(db_path) as con:
        tables = {row[0] for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    print(f"  event_snapshots 存在: {'event_snapshots' in tables}")
    print(f"  event_followups 存在: {'event_followups' in tables}")
    print(f"  已有快照日期: {tracking.snapshot_dates(db_path) if 'event_snapshots' in tables else []}")

    if not args.apply:
        print("  模式: 只报告（加 --apply 建表并记录第一份快照）")
        return 0

    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup = backup_dir / f"menduner-before-workbench-{stamp}.sqlite3"
    source = sqlite3.connect(db_path)
    with sqlite3.connect(backup) as target:
        source.backup(target)
    source.close()
    print(f"  备份完成: {backup}  ({backup.stat().st_size / 1024 / 1024:.1f} MB)")

    with connect(db_path) as con:
        tracking.ensure_schema(con)
    print("  已建表: event_snapshots / event_followups")

    result = tracking.capture(db_path)
    print(f"  已记录快照 {result['snapshotDate']}：{result['events']} 个活动身份")

    change = tracking.changes(db_path)
    print(f"  可比较: {change['comparable']}（{change.get('reason', '有历史快照可比')}）")

    with connect(db_path) as con:
        print(f"  完整性: {con.execute('PRAGMA integrity_check').fetchone()[0]}")
        print(f"  外键问题: {len(con.execute('PRAGMA foreign_key_check').fetchall())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
