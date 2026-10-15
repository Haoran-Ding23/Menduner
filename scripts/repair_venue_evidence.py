"""修复合并遗留的坏证据：venue 引用指向已删除的场馆，或状态与已记录的决策不一致。

## 问题

`merge()` 迁移了 events.venue / payload.venueId / crawler_observations，
但没有更新证据记录。于是事件的场馆引用指向保留的场馆，而证据仍指向被删除的那个。

后果：任何"把存储的声明和事件本身对照"的读取者都找不到东西 ——
知识图谱的场馆边要求 证据值 === 事件 venueId，合并后永不成立，
所以图谱只剩一个 EVENT 节点，既没有场馆也没有关联活动。

## 为什么不能只改列

服务的证据行来自 `evidence.payload` 这个 JSON，而它**自带 `value` 和 `status` 字段**。
`backend/database.py` 的 snapshot 用 `dict(json.loads(payload), ...)` 组装行，
**payload 里的值会覆盖列值**。只更新列、不更新 payload，接口返回的仍然是旧值 ——
这一点我实际踩过：改了列、重启、接口照旧返回旧值。

payload 有 22 个字段（status / method / origin / confidence / note / decidedBy / ...），
手工逐个同步必然漏。所以这里**复用管线自己的投影函数** `reproject_event`，
它从 crawler_observations 重建事件的规范 payload 与字段证据，结果与下一次采集一致。

## 用法

    python repair_venue_evidence.py            # 只报告
    python repair_venue_evidence.py --apply    # 执行
"""
import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.main import reproject_event

CANDIDATES = [
    Path(os.environ["MENDUNER_DB_PATH"]) if os.environ.get("MENDUNER_DB_PATH") else None,
    Path("/srv/menduner/data/menduner.sqlite3"),
    ROOT / "backend" / "data" / "menduner.sqlite3",
]
DB = next((p for p in CANDIDATES if p and p.exists()), CANDIDATES[-1])

ap = argparse.ArgumentParser()
ap.add_argument("--db", type=Path, default=DB)
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

con = sqlite3.connect(args.db)
con.row_factory = sqlite3.Row

current = {r["id"]: r["venue"] for r in con.execute("SELECT id, venue FROM events")}
known = {r["id"] for r in con.execute("SELECT id FROM venues")}
approved = {
    (r["event_id"], r["field"])
    for r in con.execute("SELECT event_id, field FROM review_decisions WHERE decision='Verified'")
}

# 服务的行来自 payload；对照事件的场馆，检查 payload 里的值
broken = []
for r in con.execute(
    "SELECT event_id, value, payload FROM evidence WHERE field='venueId'"
):
    eid = r["event_id"]
    want = current.get(eid)
    if want is None:
        continue
    try:
        payload = json.loads(r["payload"])
    except ValueError:
        payload = {}
    shown = payload.get("value")          # 这一列才是接口返回的
    shown_status = payload.get("status")
    wrong_value = shown != want
    stale_status = (not wrong_value) and shown_status != "Verified" and (eid, "venueId") in approved
    if not (wrong_value or stale_status):
        continue
    broken.append({
        "event_id": eid,
        "payload_value": shown,
        "column_value": json.loads(r["value"]) if r["value"] else None,
        "payload_status": shown_status,
        "want": want,
        "gone": shown not in known,
        "issue": "value" if wrong_value else "status",
    })

print(f"库: {args.db}")
print(f"事件 {len(current)}  场馆 {len(known)}")
print()
print(f"=== 需要重建的事件: {len(broken)} 个 ===")
for b in broken:
    flag = "   ← 记录的场馆已不存在" if b["gone"] else ""
    print(f"  [{b['issue']}] {b['event_id']}")
    print(f"      接口返回={b['payload_value']} (status={b['payload_status']})  "
          f"实际场馆={b['want']}{flag}")

if not broken:
    print("  无需修复")
    sys.exit(0)

if not args.apply:
    print()
    print("  DRY RUN：未改动。加 --apply 执行。")
    sys.exit(0)

con.close()
print()
print("=== 用管线自身的投影重建 ===")
for b in broken:
    reproject_event(args.db, b["event_id"])
    print(f"  已重建 {b['event_id']}")

print()
print("=== 复核（读 payload，即接口实际返回的东西）===")
con = sqlite3.connect(args.db)
con.row_factory = sqlite3.Row
left_value = left_status = 0
for r in con.execute("SELECT event_id, payload FROM evidence WHERE field='venueId'"):
    want = current.get(r["event_id"])
    if want is None:
        continue
    try:
        payload = json.loads(r["payload"])
    except ValueError:
        continue
    if payload.get("value") != want:
        left_value += 1
    elif (r["event_id"], "venueId") in approved and payload.get("status") != "Verified":
        left_status += 1
print(f"  值仍不一致: {left_value}")
print(f"  已决策但状态仍非 Verified: {left_status}")
print(f"  integrity: {con.execute('PRAGMA integrity_check').fetchone()[0]}")
print(f"  foreign_key: {len(con.execute('PRAGMA foreign_key_check').fetchall())} 个问题")
