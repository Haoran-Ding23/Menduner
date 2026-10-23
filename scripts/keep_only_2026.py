"""只保留 2026 年的活动：先备份，再按开始日期删除其余年份。

删除范围严格限定为 events 与其 evidence；场馆、酒店、地区、采集日志保留 —— 场馆是地理字典，
不该因为某年没活动就消失。开始日期为空的记录**不删**，只报告：那可能是抓取残缺，删掉会掩盖问题。
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DB = Path(os.environ["MENDUNER_DB_PATH"])
BACKUP_DIR = DB.parent / "backups"


def main() -> int:
    apply = "--apply" in sys.argv
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    total = con.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    old = con.execute("SELECT COUNT(*) FROM events WHERE startDate < '2026-01-01'").fetchone()[0]
    future = con.execute("SELECT COUNT(*) FROM events WHERE startDate >= '2027-01-01'").fetchone()[0]
    undated = con.execute("SELECT COUNT(*) FROM events WHERE startDate IS NULL").fetchone()[0]
    keep = con.execute(
        "SELECT COUNT(*) FROM events WHERE startDate >= '2026-01-01' AND startDate < '2027-01-01'"
    ).fetchone()[0]
    old_ids = [r[0] for r in con.execute(
        "SELECT id FROM events WHERE startDate < '2026-01-01' OR startDate >= '2027-01-01'")]
    marks = ",".join("?" * len(old_ids)) if old_ids else "''"
    old_evidence = con.execute(
        f"SELECT COUNT(*) FROM evidence WHERE event_id IN ({marks})", old_ids).fetchone()[0]

    print(f"  事件总数        {total}")
    print(f"  2026 年内       {keep}  （保留）")
    print(f"  2026 之前       {old}   （删除）")
    print(f"  2027 及以后     {future}（删除，同样不在「一年」范围内）")
    print(f"  无开始日期      {undated}（不删，仅报告）")
    print(f"  关联证据将删除  {old_evidence}")

    if not apply:
        print("  模式: 只报告（加 --apply 执行）")
        return 0

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup = BACKUP_DIR / f"menduner-before-2026-only-{stamp}.sqlite3"
    source = sqlite3.connect(DB)
    with sqlite3.connect(backup) as target:
        source.backup(target)
    source.close()
    print(f"  备份完成: {backup}  ({backup.stat().st_size / 1024 / 1024:.1f} MB)")

    with con:
        con.execute("DELETE FROM evidence WHERE event_id IN (SELECT id FROM events "
                    "WHERE startDate < '2026-01-01' OR startDate >= '2027-01-01')")
        deleted = con.execute("DELETE FROM events WHERE startDate < '2026-01-01' "
                              "OR startDate >= '2027-01-01'").rowcount

    after = con.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    print(f"  已删除事件 {deleted}，现在事件总数 {after}")
    print(f"  完整性: {con.execute('PRAGMA integrity_check').fetchone()[0]}")
    print(f"  外键问题: {len(con.execute('PRAGMA foreign_key_check').fetchall())}")
    print(f"  太仓: {con.execute(chr(83)+'ELECT COUNT(*) FROM events WHERE district=?', ('taicang',)).fetchone()[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
