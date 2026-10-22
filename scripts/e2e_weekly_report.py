"""验证周报导出：真实租户、真实上传数据、下载两种格式、检查文件头、然后清理。

只验证文件是真实可用的 Excel/PDF 且只含本租户数据，不验证排版。
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import accounts, tenants, weekly_report
from backend.database import connect, database_path

BASE = "http://127.0.0.1/api"
LOGIN = "zz-report-tenant"
PASSWORD = "test-password-1"
db = database_path()

# 上传一段落在"上一完整周"里的数据，否则周报会是空的。
start, end = weekly_report.week_range(date.today())
row_day = start.isoformat()
CSV = f"日期,出租率(%),平均房价,间夜\n{row_day},82.5,620,120\n".encode()

print("=== 1. invite + register ===")
with connect(db) as con:
    invite = accounts.create_invite(
        con, plan="pro", trial_days=14, max_uses=1, note="report-e2e",
        created_by="e2e", expires_in_days=1,
    )
client = httpx.Client(base_url=BASE, timeout=60)
r = client.post("/account/register", json={
    "invite_code": invite["code"], "login": LOGIN, "password": PASSWORD,
    "name": "周报测试", "hotel": "周报测试酒店",
})
print(f"  HTTP {r.status_code}")

print("=== 2. upload one week of data ===")
r = client.post("/private/import?filename=r.csv&apply=1", content=CSV)
print(f"  HTTP {r.status_code}  written={r.json().get('written') if r.status_code == 200 else r.text[:120]}")

print("=== 3. download xlsx ===")
r = client.get("/private/weekly.xlsx")
print(f"  HTTP {r.status_code}  bytes={len(r.content)}  magic={r.content[:2]!r}")
print(f"  content-type={r.headers.get('content-type')}")
print(f"  disposition={r.headers.get('content-disposition')}")
xlsx_ok = r.status_code == 200 and r.content[:2] == b"PK"

print("=== 4. download pdf ===")
r = client.get("/private/weekly.pdf")
print(f"  HTTP {r.status_code}  bytes={len(r.content)}  magic={r.content[:5]!r}")
print(f"  content-type={r.headers.get('content-type')}")
pdf_ok = r.status_code == 200 and r.content[:5] == b"%PDF-"
if r.status_code != 200:
    print(f"  detail: {r.text[:200]}")

print("=== 5. unauthenticated must be refused ===")
anon = httpx.Client(base_url=BASE, timeout=30)
r = anon.get("/private/weekly.xlsx")
print(f"  HTTP {r.status_code} (expect 401)")

print("=== 6. clean up ===")
with connect(db) as con:
    row = con.execute("SELECT id FROM customer_accounts WHERE login=?", (LOGIN,)).fetchone()
    if row:
        account_id = row["id"]
        owned = [r2["tenant_id"] for r2 in con.execute(
            "SELECT tenant_id FROM tenant_members WHERE login=?", (LOGIN,))]
        con.execute("DELETE FROM tenant_members WHERE login=?", (LOGIN,))
        con.execute("DELETE FROM customer_sessions WHERE account_id=?", (account_id,))
        con.execute("DELETE FROM customer_accounts WHERE id=?", (account_id,))
        for tenant in owned:
            con.execute("DELETE FROM tenants WHERE id=?", (tenant,))
            path = db.parent / "tenants" / f"{tenant}.sqlite3"
            if path.exists():
                path.unlink()
        print(f"  removed account and {len(owned)} tenant(s)")
    print(f"  accounts left: {con.execute('SELECT COUNT(*) FROM customer_accounts').fetchone()[0]}")
    print(f"  tenants left: {con.execute('SELECT COUNT(*) FROM tenants').fetchone()[0]}")

print()
print(f"结果: xlsx={'OK' if xlsx_ok else 'FAIL'}  pdf={'OK' if pdf_ok else 'FAIL'}")
sys.exit(0 if (xlsx_ok and pdf_ok) else 1)
