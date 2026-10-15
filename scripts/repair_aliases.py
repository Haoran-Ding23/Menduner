"""修复别名文件：补 canonical_row，清理指向不存在场馆的条目。

背景：write_alias() 原来不写 canonical_row，而采集管线要求能通过
canonical_venue_rows() 找到主场馆，否则抛
"Venue alias points at a canonical venue that is not declared"。
这次合并产生的 11 条别名因此缺少该字段。

只读数据库；写别名文件。
"""
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DB_CANDIDATES = [
    Path(os.environ["MENDUNER_DB_PATH"]) if os.environ.get("MENDUNER_DB_PATH") else None,
    Path("/srv/menduner/data/menduner.sqlite3"),
    ROOT / "backend" / "data" / "menduner.sqlite3",
]
DB = next((p for p in DB_CANDIDATES if p and p.exists()), DB_CANDIDATES[-1])
ALIAS_PATH = Path(os.environ.get("MENDUNER_VENUE_ALIASES", ROOT / "crawler" / "venue_aliases.json"))

DRY = "--dry-run" in sys.argv

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
venues = {}
for r in con.execute("SELECT id, payload FROM venues"):
    venues[r["id"]] = json.loads(r["payload"])

document = json.loads(ALIAS_PATH.read_text(encoding="utf-8"))
aliases = document.get("aliases", [])

print(f"库: {DB}")
print(f"别名文件: {ALIAS_PATH}")
print(f"现有别名: {len(aliases)} 条")
print()

kept = []
dropped = []
filled = 0
for row in aliases:
    canonical_id = row.get("canonical_id")
    if canonical_id not in venues:
        dropped.append((row.get("alias_id"), canonical_id, row.get("name")))
        continue
    if not isinstance(row.get("canonical_row"), dict):
        row = dict(row)
        row["canonical_row"] = venues[canonical_id]
        filled += 1
    kept.append(row)

print(f"补上 canonical_row: {filled} 条")
print(f"删除（主场馆不存在）: {len(dropped)} 条")
for alias_id, canonical_id, name in dropped:
    print(f"    {str(name)[:32]:34s} alias={alias_id} -> canonical={canonical_id}")

if dropped:
    print()
    print("（这些别名指向的场馆在这次合并中被并掉了，别名已经没有意义）")

# 重复 alias_id 只保留一条（后写的覆盖先写的）
by_alias = {}
for row in kept:
    by_alias[row["alias_id"]] = row
if len(by_alias) != len(kept):
    print(f"去重 alias_id: {len(kept)} -> {len(by_alias)}")
kept = list(by_alias.values())

document["aliases"] = kept

print()
print(f"最终别名: {len(kept)} 条")
for row in kept:
    nm = row.get("name") or row.get("alias_id")
    has = "有" if isinstance(row.get("canonical_row"), dict) else "无"
    print(f"  {str(nm)[:34]:36s} -> {row['canonical_id']}  canonical_row={has}")

if DRY:
    print()
    print("  --dry-run：未写入")
else:
    ALIAS_PATH.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print()
    print("  已写入")

    # 复核：管线用的读取函数能否返回所有主场馆
    from crawler.venues import canonical_venue_rows
    declared = canonical_venue_rows(ALIAS_PATH)
    ids = [r["id"] for r in declared]
    missing = [row["canonical_id"] for row in kept if row["canonical_id"] not in ids]
    print(f"  canonical_venue_rows() 返回 {len(declared)} 个主场馆")
    if missing:
        print(f"  !!! 仍缺: {missing}")
        sys.exit(1)
    print("  所有别名的主场馆都能被解析 ✓")
