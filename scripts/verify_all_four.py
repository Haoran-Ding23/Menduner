"""收官验证：一次覆盖四项功能的可观察证据。

只读检查，不改任何数据。每项都取生产库或 HTTP 状态作为证据，而不是凭印象。
"""
import json
import sqlite3
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, "/srv/menduner")

DB = Path("/srv/menduner/data/menduner.sqlite3")
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

print("=== ① 商圈自动化 ===")
areas = [r for r in con.execute("SELECT payload FROM districts")
         if json.loads(r["payload"]).get("kind") == "business_area"]
with_coords = [a for a in areas if (json.loads(a["payload"]).get("coordinates") or {}).get("lng")]
print(f"  商圈 {len(areas)} 个，其中有中心点 {len(with_coords)}")
hotels = [json.loads(r["payload"]) for r in con.execute("SELECT payload FROM hotels")]
assigned = [h for h in hotels if (h.get("businessArea") or {}).get("status") == "Computed"]
out_of_range = [h for h in hotels if (h.get("businessArea") or {}).get("status") == "OutOfRange"]
print(f"  酒店 {len(hotels)} 家：自动归属 {len(assigned)}，超出半径如实不归属 {len(out_of_range)}")
sample = assigned[0]["businessArea"] if assigned else None
if sample:
    print(f"  样例归属: {sample['name']} {sample['distanceKm']} km "
          f"(阈值 {sample['thresholdKm']} km, 状态 {sample['status']})")

print()
print("=== ③ 团队与成员 ===")
tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
print(f"  tenants 表: {'tenants' in tables}   tenant_members 表: {'tenant_members' in tables}")
print(f"  已注册客户账号: {con.execute('SELECT COUNT(*) FROM customer_accounts').fetchone()[0]}")
print(f"  已建租户: {con.execute('SELECT COUNT(*) FROM tenants').fetchone()[0]}")


def status(path):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1/api/{path}", timeout=10) as r:
            return r.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except Exception as exc:  # network
        return f"error {type(exc).__name__}"


print()
print("=== 未登录时四个受保护接口必须为 401 ===")
for path in ("private/metrics", "private/weekly.xlsx", "private/weekly.pdf", "tenant/members"):
    print(f"  GET /api/{path} -> {status(path)}")

print()
print("=== 公开页面可用（页面不在 /api 前缀下）===")


def page_status(path):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1{path}", timeout=10) as r:
            return r.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except Exception as exc:
        return f"error {type(exc).__name__}"


for page in ("/", "/map", "/private", "/evidence"):
    print(f"  {page} -> {page_status(page)}")

print()
print("=== 数据完整性 ===")
print(f"  integrity: {con.execute('PRAGMA integrity_check').fetchone()[0]}")
print(f"  foreign_key: {len(con.execute('PRAGMA foreign_key_check').fetchall())} problems")
print(f"  events: {con.execute('SELECT COUNT(*) FROM events').fetchone()[0]}")
print(f"  venues: {con.execute('SELECT COUNT(*) FROM venues').fetchone()[0]}")
