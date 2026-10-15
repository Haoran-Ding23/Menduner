"""场馆归并执行脚本。

每条合并都写 reviewer 和 reason —— 这是设计要求的：合并是一个身份判定，
必须留下决策记录，而不是自动推断。

用法:
    python merge_venues.py --dry-run   # 只看会做什么
    python merge_venues.py             # 真执行
"""
import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import venues as venue_store
from crawler.venue_duplicates import detect

# 服务器上是 /srv/menduner/data（由 MENDUNER_DB_PATH 指定），
# 本地是 backend/data。两者都试，取存在的那个，避免脚本只在一边能用。
DB_CANDIDATES = [
    Path(os.environ["MENDUNER_DB_PATH"]) if os.environ.get("MENDUNER_DB_PATH") else None,
    Path("/srv/menduner/data/menduner.sqlite3"),
    ROOT / "backend" / "data" / "menduner.sqlite3",
]
DB = next((p for p in DB_CANDIDATES if p and p.exists()), DB_CANDIDATES[-1])
REVIEWER = "menduner-lead"
REASON_BASE = "同一场馆的两个名称行；合并后事件引用与坐标归到一行。"


def show(con, label, vid):
    r = con.execute("SELECT payload FROM venues WHERE id=?", (vid,)).fetchone()
    if not r:
        print(f"    {label}: (不存在) {vid}")
        return
    p = json.loads(r["payload"])
    n = con.execute("SELECT COUNT(*) FROM events WHERE venue=?", (vid,)).fetchone()[0]
    print(f"    {label}: {p.get('name')}")
    print(f"       地址={p.get('address')}  坐标={'有' if p.get('coordinates') else '无'}  活动={n}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DB)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row

    venues = []
    for r in con.execute("SELECT id, payload FROM venues"):
        p = json.loads(r["payload"])
        venues.append({"id": r["id"], "name": p.get("name"), "address": p.get("address"),
                       "coordinates": p.get("coordinates")})
    usage = {r["venue"]: r["n"] for r in con.execute(
        "SELECT venue, COUNT(*) n FROM events GROUP BY venue")}

    cands = detect(venues, usage)

    # 人工复核后的决定。检测器只是提议，这里记录的是"接受哪些、为什么"。
    #
    # 跳过众戏剧文化艺术空间 -> 苏州狮山大剧院: 名称完全不同,只是坐标接近。
    # 坐标接近说明同址,不说明同名 —— 同一栋楼里的两个空间是两个场馆,不能合并。
    SKIP_NAMES = {"众戏剧文化艺术空间"}

    accepted = [c for c in cands if c.alias_name not in SKIP_NAMES]
    skipped = [c for c in cands if c.alias_name in SKIP_NAMES]

    print(f"检测器给出 {len(cands)} 组候选")
    print(f"  接受 {len(accepted)} 组")
    print(f"  跳过 {len(skipped)} 组")
    for c in skipped:
        d = c.as_dict()
        print(f"    [跳过/{d['signal']}] {d['alias_name']} -> {d['canonical_name']}")
        print(f"       理由: 名称不同，仅坐标接近；同址不等于同场馆")

    print()
    print("=" * 74)
    print("将执行的合并")
    print("=" * 74)
    for c in accepted:
        d = c.as_dict()
        print()
        print(f"  [{d['signal']}] {d['alias_name']}  ->  {d['canonical_name']}")
        show(con, "别名", d["alias_id"])
        show(con, "主名", d["canonical_id"])
        if d["notes"]:
            for n in d["notes"]:
                print(f"       注: {n}")

    if args.dry_run:
        print()
        print(f"  --dry-run：未改动任何数据（{len(accepted)} 组待执行）")
        return

    print()
    print("=" * 74)
    print("执行")
    print("=" * 74)
    done = 0
    for c in accepted:
        d = c.as_dict()
        try:
            result = venue_store.merge(
                args.db,
                alias_id=d["alias_id"],
                canonical_id=d["canonical_id"],
                reviewer=REVIEWER,
                reason=f"{REASON_BASE} 证据: {d['signal']}"
                       + (f"，距离 {d['distance_km']}km" if d["distance_km"] is not None else ""),
                revert=False,
            )
            moved = result.get("events_moved", result.get("eventsMoved", "?"))
            print(f"  ✓ {d['alias_name'][:36]:38s} -> {d['canonical_name'][:28]:30s} 迁移事件 {moved}")
            done += 1
        except Exception as exc:
            print(f"  ✗ {d['alias_name'][:36]:38s} 失败: {type(exc).__name__}: {exc}")

    print()
    print(f"  完成 {done} 组")

    # 复核：合并后再检测一次，看还剩什么
    con2 = sqlite3.connect(args.db)
    con2.row_factory = sqlite3.Row
    venues2 = []
    for r in con2.execute("SELECT id, payload FROM venues"):
        p = json.loads(r["payload"])
        venues2.append({"id": r["id"], "name": p.get("name"), "address": p.get("address"),
                        "coordinates": p.get("coordinates")})
    usage2 = {r["venue"]: r["n"] for r in con2.execute(
        "SELECT venue, COUNT(*) n FROM events GROUP BY venue")}
    left = detect(venues2, usage2)
    print()
    print(f"  合并后场馆数: {len(venues2)}（原 {len(venues)}）")
    print(f"  剩余候选: {len(left)} 组")
    for c in left:
        d = c.as_dict()
        print(f"    [{d['signal']}] {d['alias_name'][:34]} -> {d['canonical_name'][:30]}")


if __name__ == "__main__":
    main()
