"""把社交导入的活动从本地 scratch 库并入生产库。

规则：
  * 场馆优先按**名称精确匹配**生产已有场馆（例如「太仓大剧院」已在库且坐标已核验），
    匹配不到才新建，且**不带坐标** —— 社交笔记没有坐标，猜一个就是编造；
  * 事件保留原 id、原来源、原核验状态（Needs Review / Conflicting），不做任何放宽；
  * 证据行一并搬过去，字段值里的原文引用不丢，复核时能点回笔记；
  * 已存在的 id 直接跳过，可重复执行。

    python -X utf8 scripts/import_xhs_to_production.py --scratch scratch.sqlite3 [--apply]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database import connect, database_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scratch", default="scratch.sqlite3")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    scratch = sqlite3.connect(args.scratch)
    scratch.row_factory = sqlite3.Row

    events = [dict(r) for r in scratch.execute(
        "SELECT id,name,category,startDate,endDate,venue,district,source,"
        "verification_status,payload FROM events")]
    event_ids = [e["id"] for e in events]
    marks = ",".join("?" * len(event_ids))
    evidence = [dict(r) for r in scratch.execute(
        f"SELECT * FROM evidence WHERE event_id IN ({marks})", event_ids)]
    venues = {r["id"]: json.loads(r["payload"]) for r in scratch.execute(
        "SELECT id,payload FROM venues")}

    print(f"  待导入：事件 {len(events)}，证据 {len(evidence)}，场馆 {len(venues)}")

    added_events = added_evidence = linked_venues = created_venues = 0
    with connect(database_path()) as con:
        # 生产已有场馆：名称 -> id，用于把社交事件挂到已核验的场馆上
        existing = {}
        for row in con.execute("SELECT id, payload FROM venues"):
            payload = json.loads(row["payload"])
            name = (payload.get("name") or "").strip()
            if name:
                existing.setdefault(name, row["id"])

        venue_map: dict[str, str] = {}
        for venue_id, payload in venues.items():
            name = (payload.get("name") or "").strip()
            if name in existing:
                venue_map[venue_id] = existing[name]
                linked_venues += 1
                continue
            # 归属地区取引用它的那批事件里最常见的 district
            districts = [e["district"] for e in events if e["venue"] == venue_id and e["district"]]
            district = max(set(districts), key=districts.count) if districts else None
            if args.apply:
                new_payload = {
                    "id": venue_id,
                    "name": name,
                    "address": None,
                    "districtId": district,
                    "districtDemo": False,
                    "coordinates": None,
                    "source": "xiaohongshu-note-import",
                    "note": "来自社交笔记的场馆名，暂无坐标；坐标需人工核验后补",
                }
                con.execute("INSERT OR IGNORE INTO venues(id,payload) VALUES(?,?)",
                            (venue_id, json.dumps(new_payload, ensure_ascii=False)))
            venue_map[venue_id] = venue_id
            created_venues += 1

        for event in events:
            exists = con.execute("SELECT 1 FROM events WHERE id=?", (event["id"],)).fetchone()
            if exists:
                continue
            payload = json.loads(event["payload"])
            venue_id = venue_map.get(event["venue"] or "")
            if venue_id:
                payload["venueId"] = venue_id
            payload["districtId"] = event["district"]
            if args.apply:
                con.execute(
                    "INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (event["id"], event["name"], event["category"], event["startDate"],
                     event["endDate"], venue_id, event["district"], event["source"],
                     event["verification_status"],
                     json.dumps(payload, ensure_ascii=False)),
                )
            added_events += 1

        for row in evidence:
            if args.apply:
                # The production evidence table has eight columns; the scratch copy carries an
                # extra one from the import run.
                con.execute(
                    "INSERT OR IGNORE INTO evidence"
                    "(id,event_id,entity_id,field,value,source_url,verification_status,payload)"
                    " VALUES(?,?,?,?,?,?,?,?)",
                    (row["id"], row["event_id"], row["entity_id"], row["field"], row["value"],
                     row["source_url"], row["verification_status"], row["payload"]),
                )
            added_evidence += 1

        if args.apply:
            total_events = con.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            total_venues = con.execute("SELECT COUNT(*) FROM venues").fetchone()[0]
            print(f"  生产库现在：事件 {total_events}，场馆 {total_venues}")

    print(f"  场馆：复用已有 {linked_venues}，新建 {created_venues}")
    print(f"  事件：新增 {added_events}，证据 {added_evidence}")
    print(f"  模式: {'写入' if args.apply else '只报告'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
