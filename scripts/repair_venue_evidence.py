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

def decision_value(raw):
    """The venue id a review decision names.

    ``review_decisions.reviewed_value`` stores plain text, not JSON - unlike the evidence
    payload, where the same value is a JSON-encoded string. Parsing the decision with
    ``json.loads`` therefore fails on every id, and a failure read as None looks exactly like
    "this decision names a venue that no longer exists": the first version of this repair
    classified all 112 healthy decisions as broken and would have rewritten every one of them.
    Text is taken as written; only a JSON-encoded string is decoded.
    """
    if raw is None:
        return None
    text = raw.strip()
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        try:
            return json.loads(text)
        except ValueError:
            return text
    return text


def payload_value(raw):
    """The venue id an evidence payload column holds, which IS JSON-encoded."""
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return text


current = {r["id"]: r["venue"] for r in con.execute("SELECT id, venue FROM events")}
known = {r["id"] for r in con.execute("SELECT id FROM venues")}
# Events a human has already settled for this field, regardless of which value they approved.
approved = {
    (r["event_id"], r["field"])
    for r in con.execute("SELECT event_id, field FROM review_decisions WHERE decision='Verified'")
}

# Decisions whose reviewed_value no longer matches the event's venue. A merge rewrote the
# event but left the decision naming the venue it deleted, and a decision only applies when
# its reviewed_value equals the event's current value - so the approval silently stopped
# working and the field fell back to Needs Review despite having been settled by a human.
#
# A decision with no value at all is left alone: it names nothing, so there is nothing to
# repoint, and treating "empty" as "stale" is how the first attempt went wrong.
stale_decisions = {}
empty_decisions = 0
for r in con.execute(
    "SELECT event_id, reviewed_value FROM review_decisions "
    "WHERE field='venueId' AND decision='Verified'"
):
    want = current.get(r["event_id"])
    if want is None:
        continue
    have = decision_value(r["reviewed_value"])
    if have is None:
        empty_decisions += 1
        continue
    if have != want:
        stale_decisions[r["event_id"]] = {"event_id": r["event_id"], "from": have,
                                          "to": want, "gone": have not in known}

# 服务的行来自 payload；对照事件的场馆，检查 payload 里的值
broken = {}
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
    # An event with a stale decision also needs a rebuild, even when its payload value is
    # already correct: the rebuild is what re-applies the corrected decision.
    decision_stale = eid in stale_decisions
    if not (wrong_value or stale_status or decision_stale):
        continue
    broken[eid] = {
        "event_id": eid,
        "payload_value": shown,
        "column_value": payload_value(r["value"]),
        "payload_status": shown_status,
        "want": want,
        "gone": shown not in known,
        "issue": "value" if wrong_value else ("decision" if decision_stale else "status"),
    }
broken = list(broken.values())

print(f"库: {args.db}")
print(f"事件 {len(current)}  场馆 {len(known)}")
print()
print(f"=== 记录了旧场馆的人工决策: {len(stale_decisions)} 条 ===")
for d in stale_decisions.values():
    flag = "  ← 决策指向已不存在的场馆" if d["gone"] else ""
    print(f"  {d['event_id']}  {d['from']} -> {d['to']}{flag}")
if empty_decisions:
    print(f"  （另有 {empty_decisions} 条决策没有记录值，不动它们）")
print()
print(f"=== 需要重建的事件: {len(broken)} 个 ===")
for b in broken:
    flag = "   ← 记录的场馆已不存在" if b["gone"] else ""
    print(f"  [{b['issue']}] {b['event_id']}")
    print(f"      接口返回={b['payload_value']} (status={b['payload_status']})  "
          f"实际场馆={b['want']}{flag}")

if not broken and not stale_decisions:
    print("  无需修复")
    sys.exit(0)

if not args.apply:
    print()
    print("  DRY RUN：未改动。加 --apply 执行。")
    sys.exit(0)

con.close()
print()
print("=== 1. 修正记录了旧场馆的人工决策 ===")
if stale_decisions:
    dec = sqlite3.connect(args.db)
    for d in stale_decisions.values():
        dec.execute("UPDATE review_decisions SET reviewed_value=? WHERE event_id=? AND field='venueId'",
                    (d["to"], d["event_id"]))
    dec.commit()
    dec.close()
    print(f"  已修正 {len(stale_decisions)} 条")
else:
    print("  无需修正")

print()
print("=== 2. 用管线自身的投影重建事件 ===")
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
