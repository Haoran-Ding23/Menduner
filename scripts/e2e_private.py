"""End-to-end check of the private-data chain against the running API, then clean up.

Verifies the four things that matter together: registration gives the account a tenant, the
import previews before writing, apply writes only into that hotel's own database, and the read
endpoint returns that hotel's rows. Removes its own test account and ledger afterwards so
production is left as it was found.
"""
import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import accounts
from backend.database import connect, database_path

BASE = "http://127.0.0.1/api"
LOGIN = "zz-e2e-tenant"
PASSWORD = "test-password-1"
CSV = (
    "日期,出租率(%),平均房价,间夜\n"
    "2026-10-01,82.5,620,120\n"
    "2026-10-02,78,610,115\n"
    "2026-10-03,150,600,100\n"
)

db = database_path()

print("=== 1. invite ===")
with connect(db) as con:
    invite = accounts.create_invite(
        con, plan="pro", trial_days=14, max_uses=1, note="e2e",
        created_by="e2e", expires_in_days=1,
    )
print(f"  code: {invite['code']}")

client = httpx.Client(base_url=BASE, timeout=30)
print()
print("=== 2. register (should create the tenant) ===")
r = client.post("/account/register", json={
    "invite_code": invite["code"], "login": LOGIN, "password": PASSWORD,
    "name": "端到端测试", "hotel": "端到端测试酒店",
})
print(f"  HTTP {r.status_code}")
state = r.json() if r.status_code == 200 else {}
print(f"  authenticated: {state.get('authenticated')}")

print()
print("=== 2b. does the database agree the account has a tenant? ===")
from backend import tenants as tenant_model
with connect(db) as con:
    row = con.execute("SELECT id, login FROM customer_accounts WHERE login=?", (LOGIN,)).fetchone()
    print(f"  account row: {dict(row) if row else None}")
    print(f"  tenant_of_login: {tenant_model.tenant_of_login(db, LOGIN)}")
    print(f"  members: {tenant_model.members_of(db, tenant_model.tenant_of_login(db, LOGIN) or '')}")
    print(f"  session row: {con.execute('SELECT COUNT(*) FROM customer_sessions').fetchone()[0]} sessions")
    print(f"  cookie in client: {dict(client.cookies)}")

print()
print("=== 3. import preview (apply=0) ===")
r = client.post("/private/import?filename=e2e.csv&apply=0", content=CSV.encode())
print(f"  HTTP {r.status_code}")
preview = r.json() if r.status_code == 200 else {"detail": r.text[:200]}
if r.status_code == 200:
    print(f"  tenant: {preview.get('tenant')}")
    print(f"  mapping: {preview.get('mapping')}")
    print(f"  rowsRead: {preview.get('rowsRead')}  accepted: {preview.get('acceptedCount')}")
    for issue in preview.get("issues", []):
        print(f"    row {issue['row']}: {issue['reason']}")
else:
    print(f"  detail: {preview.get('detail')}")

print()
print("=== 4. apply (apply=1) ===")
r = client.post("/private/import?filename=e2e.csv&apply=1", content=CSV.encode())
print(f"  HTTP {r.status_code}")
applied = r.json() if r.status_code == 200 else {}
print(f"  written: {applied.get('written')}  dryRun: {applied.get('dryRun')}")

print()
print("=== 5. read back this hotel's rows ===")
r = client.get("/private/metrics")
print(f"  HTTP {r.status_code}")
metrics = r.json() if r.status_code == 200 else {}
if r.status_code != 200:
    print(f"  detail: {r.text[:220]}")
print(f"  tenant: {metrics.get('tenant')}  count: {metrics.get('count')}")
for row in metrics.get("rows", [])[:6]:
    print(f"    {row['metric']:16s} {row['period_start']}  {row['value']}")

print()
print("=== 6. clean up the test account and its ledger ===")
with connect(db) as con:
    row = con.execute("SELECT id FROM customer_accounts WHERE login=?", (LOGIN,)).fetchone()
    if row:
        account_id = row["id"]
        tenants_rows = [r2["tenant_id"] for r2 in con.execute(
            "SELECT tenant_id FROM tenant_members WHERE login=?", (LOGIN,))]
        con.execute("DELETE FROM tenant_members WHERE login=?", (LOGIN,))
        con.execute("DELETE FROM customer_sessions WHERE account_id=?", (account_id,))
        con.execute("DELETE FROM customer_accounts WHERE id=?", (account_id,))
        for tenant in tenants_rows:
            con.execute("DELETE FROM tenants WHERE id=?", (tenant,))
            path = db.parent / "tenants" / f"{tenant}.sqlite3"
            if path.exists():
                path.unlink()
            print(f"  removed tenant {tenant} and its file")
        print(f"  removed account {LOGIN}")
    else:
        print("  account not found (nothing to clean)")
    print(f"  tenants left: {con.execute('SELECT COUNT(*) FROM tenants').fetchone()[0]}")
    print(f"  accounts left: {con.execute('SELECT COUNT(*) FROM customer_accounts').fetchone()[0]}")
