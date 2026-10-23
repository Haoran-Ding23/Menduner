"""每日快照：记录当天每个活动身份的状态，供工作台比较「本周变化」。

    python -X utf8 scripts/capture_snapshot.py

建议挂在每日采集之后（cron 或 systemd timer），一天一次即可：
    5 8 * * *  cd /srv/menduner && venv/bin/python -X utf8 scripts/capture_snapshot.py

同一天重复执行会覆盖为最新值（幂等），因此手动补跑安全。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import tracking
from backend.database import connect, database_path


def main() -> int:
    db_path = database_path()
    result = tracking.capture(db_path)
    print(f"  快照 {result['snapshotDate']}：{result['events']} 个活动身份")
    change = tracking.changes(db_path)
    if change["comparable"]:
        print(
            f"  与 {change['from']} 相比：新增 {len(change['added'])}、改期 "
            f"{len(change['rescheduled'])}、取消 {len(change['cancelled'])}、"
            f"信息变化 {len(change['changed'])}"
        )
    else:
        print(f"  {change.get('reason')}")
    with connect(db_path) as con:
        print(f"  完整性: {con.execute('PRAGMA integrity_check').fetchone()[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
