"""工作台数据层：活动快照与酒店跟进状态。

这两张表放在一起，是因为它们回答同一个问题的一半：**「和我上次看到的相比，什么变了」** 和
**「我决定怎么处理」**。没有快照就只能显示「今天有什么」，用户无法知道哪个是新冒出来的；
没有跟进状态，用户看完就忘，周报也无法列出待办。

## event_snapshots（公开数据，按天留存）

每行是「某一天，某个活动身份的样子」。按 canonical_id 记录，因此同一活动被多个来源收录时只留
一条快照，和统计口径一致（backend/dedupe.py）。

只记身份与时间，不复制正文：快照的用途是**比较**，不是备份。原始记录仍在 events 与 evidence 里。

## event_followups（按酒店隔离）

酒店对某个活动的处理态度：关注 / 忽略 / 待跟进 / 已跟进，可带备注。按 tenant_id 隔离，租户从
会话解析（不接收请求里的 tenant 参数），与私有经营数据同一套边界。

## 没有历史时怎么办

`changes()` 在只有一份快照时返回 `comparable=False` 和「尚无可比较记录」，界面必须照此显示，
而不是把「无法比较」渲染成「没有变化」。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from backend.database import connect

DDL = """
CREATE TABLE IF NOT EXISTS event_snapshots (
  snapshot_date TEXT NOT NULL,
  event_key     TEXT NOT NULL,
  name          TEXT NOT NULL,
  start_date    TEXT,
  end_date      TEXT,
  status        TEXT,
  captured_at   TEXT NOT NULL,
  PRIMARY KEY (snapshot_date, event_key)
);
CREATE INDEX IF NOT EXISTS event_snapshots_key_idx ON event_snapshots(event_key);

CREATE TABLE IF NOT EXISTS event_followups (
  tenant_id  TEXT NOT NULL,
  event_key  TEXT NOT NULL,
  state      TEXT NOT NULL,
  adopted    TEXT,
  feedback   TEXT,
  note       TEXT,
  updated_at TEXT NOT NULL,
  updated_by TEXT,
  PRIMARY KEY (tenant_id, event_key)
);
CREATE INDEX IF NOT EXISTS event_followups_tenant_idx ON event_followups(tenant_id);
"""

STATES = ("watching", "ignored", "todo", "done")

# 是否采纳建议：unknown 是默认值，不是「未采纳」——没有反馈时不能说用户拒绝。
ADOPTED = ("unknown", "adopted", "declined")
ADOPTED_LABELS = {"unknown": "未知", "adopted": "已采纳", "declined": "未采纳"}
STATE_LABELS = {
    "watching": "关注",
    "ignored": "忽略",
    "todo": "待跟进",
    "done": "已跟进",
}


def ensure_schema(con) -> None:
    con.executescript(DDL)
    # 采纳字段是后加的：已存在的表要补列，否则旧库上调用 set_followup 会报 no such column。
    columns = {row[1] for row in con.execute("PRAGMA table_info(event_followups)")}
    for name in ("adopted", "feedback"):
        if name not in columns:
            con.execute(f"ALTER TABLE event_followups ADD COLUMN {name} TEXT")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def today_beijing() -> str:
    parts = datetime.now(timezone.utc).isoformat()
    # 与前端一致：按北京时间取日期，避免 UTC 跨零点把快照记到前一天。
    from datetime import timedelta
    utc = datetime.fromisoformat(parts)
    return (utc + timedelta(hours=8)).date().isoformat()


def _event_key(row) -> str:
    """活动身份：优先 canonical_id（去重后），没有该列时退回自身 id。"""
    canonical = row["canonical_id"] if "canonical_id" in row.keys() else None
    return canonical or row["id"]


def capture(db_path: Path, snapshot_date: str | None = None) -> dict:
    """把当前每个活动身份的状态写成当天快照。幂等：同一天重复运行覆盖为最新值。"""
    stamp = snapshot_date or today_beijing()
    captured_at = now_iso()
    with connect(db_path) as con:
        ensure_schema(con)
        columns = {row[1] for row in con.execute("PRAGMA table_info(events)")}
        has_canonical = "canonical_id" in columns
        query = ("SELECT id, canonical_id, name, startDate, endDate, verification_status "
                 "FROM events") if has_canonical else \
                ("SELECT id, id AS canonical_id, name, startDate, endDate, verification_status "
                 "FROM events")
        rows = list(con.execute(query))
        # 同一身份可能有多条记录：取规范记录（id == canonical）的字段，保证快照稳定。
        chosen: dict[str, dict] = {}
        for row in rows:
            key = _event_key(row)
            if key in chosen and row["id"] != key:
                continue
            chosen[key] = {
                "snapshot_date": stamp,
                "event_key": key,
                "name": row["name"] or "",
                "start_date": row["startDate"],
                "end_date": row["endDate"],
                "status": row["verification_status"],
                "captured_at": captured_at,
            }
        con.executemany(
            "INSERT INTO event_snapshots(snapshot_date,event_key,name,start_date,end_date,"
            "status,captured_at) VALUES(:snapshot_date,:event_key,:name,:start_date,:end_date,"
            ":status,:captured_at) ON CONFLICT(snapshot_date,event_key) DO UPDATE SET "
            "name=excluded.name,start_date=excluded.start_date,end_date=excluded.end_date,"
            "status=excluded.status,captured_at=excluded.captured_at",
            list(chosen.values()),
        )
        return {"snapshotDate": stamp, "events": len(chosen)}


def snapshot_dates(db_path: Path) -> list[str]:
    with connect(db_path) as con:
        ensure_schema(con)
        return [row[0] for row in con.execute(
            "SELECT DISTINCT snapshot_date FROM event_snapshots ORDER BY snapshot_date")]


def changes(db_path: Path, since: str | None = None, until: str | None = None) -> dict:
    """比较窗口首尾两份快照，给出新增 / 取消 / 改期 / 信息变化。

    只有一份快照时无法比较，返回 comparable=False —— 界面必须显示「尚无可比较记录」，
    而不是「没有变化」，这两件事对用户的含义完全不同。
    """
    with connect(db_path) as con:
        ensure_schema(con)
        dates = [row[0] for row in con.execute(
            "SELECT DISTINCT snapshot_date FROM event_snapshots ORDER BY snapshot_date")]
        if not dates:
            return {"comparable": False, "reason": "尚无快照记录", "dates": [],
                    "added": [], "cancelled": [], "rescheduled": [], "changed": []}
        # until 让调用方指定比较终点。历史区间报表必须传它：否则会把「查询截止日之后」才发生的
        # 变化算进历史差分（例如导出 10-19..10-21，却把 10-24 才出现的取消当成区间内变化）。
        candidates = [value for value in dates if until is None or value <= until]
        if not candidates:
            candidates = dates[:1]
        base_date = since if since in candidates else candidates[0]
        latest_date = candidates[-1]
        if base_date == latest_date:
            return {"comparable": False, "reason": "尚无可比较记录（只有一份快照）",
                    "dates": dates, "added": [], "cancelled": [], "rescheduled": [], "changed": []}

        def load(date: str) -> dict[str, dict]:
            return {
                row["event_key"]: dict(row)
                for row in con.execute(
                    "SELECT event_key,name,start_date,end_date,status FROM event_snapshots "
                    "WHERE snapshot_date=?", (date,))
            }

        before, after = load(base_date), load(latest_date)

    added = [after[key] for key in after if key not in before]
    cancelled = [before[key] for key in before if key not in after]
    rescheduled, changed = [], []
    for key in after:
        if key not in before:
            continue
        old, new = before[key], after[key]
        if (old["start_date"], old["end_date"]) != (new["start_date"], new["end_date"]):
            rescheduled.append({"before": old, "after": new})
        elif old["name"] != new["name"] or old["status"] != new["status"]:
            changed.append({"before": old, "after": new})
    return {
        "comparable": True, "from": base_date, "to": latest_date, "dates": dates,
        "added": added, "cancelled": cancelled,
        "rescheduled": rescheduled, "changed": changed,
    }


def set_followup(db_path: Path, *, tenant_id: str, event_key: str, state: str,
                 note: str | None = None, actor: str | None = None,
                 adopted: str | None = None, feedback: str | None = None) -> dict:
    if state not in STATES:
        raise ValueError(f"状态必须是 {'/'.join(STATES)} 之一")
    if adopted is not None and adopted not in ADOPTED:
        raise ValueError(f"采纳状态必须是 {'/'.join(ADOPTED)} 之一")
    with connect(db_path) as con:
        ensure_schema(con)
        con.execute(
            "INSERT INTO event_followups(tenant_id,event_key,state,adopted,feedback,note,"
            "updated_at,updated_by) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(tenant_id,event_key) "
            "DO UPDATE SET state=excluded.state,adopted=COALESCE(excluded.adopted,adopted),"
            "feedback=COALESCE(excluded.feedback,feedback),note=excluded.note,"
            "updated_at=excluded.updated_at,updated_by=excluded.updated_by",
            (tenant_id, event_key, state, adopted, feedback, note, now_iso(), actor),
        )
    return {"tenant": tenant_id, "eventKey": event_key, "state": state,
            "stateLabel": STATE_LABELS[state], "note": note,
            "adopted": adopted or "unknown",
            "adoptedLabel": ADOPTED_LABELS[adopted or "unknown"]}


def clear_followup(db_path: Path, *, tenant_id: str, event_key: str) -> bool:
    with connect(db_path) as con:
        ensure_schema(con)
        cursor = con.execute(
            "DELETE FROM event_followups WHERE tenant_id=? AND event_key=?",
            (tenant_id, event_key))
        return cursor.rowcount > 0


def list_followups(db_path: Path, tenant_id: str) -> list[dict]:
    with connect(db_path) as con:
        ensure_schema(con)
        return [
            dict(row,
                 stateLabel=STATE_LABELS.get(row["state"], row["state"]),
                 adopted=row["adopted"] or "unknown",
                 adoptedLabel=ADOPTED_LABELS.get(row["adopted"] or "unknown", "未知"))
            for row in con.execute(
                "SELECT event_key AS eventKey, state, adopted, feedback, note, "
                "updated_at AS updatedAt, updated_by AS updatedBy FROM event_followups "
                "WHERE tenant_id=? ORDER BY updated_at DESC", (tenant_id,))
        ]
