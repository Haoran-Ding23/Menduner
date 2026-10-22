"""Give every existing customer account its own private ledger.

The tenant model arrived after the accounts did, so accounts created earlier have no hotel and
the private endpoints answer 403 for them. This backfills them; new registrations create their
tenant directly and do not need it.

Idempotent: an account that already belongs to a hotel keeps it, so running this twice is safe.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import accounts, tenants
from backend.database import connect, database_path

ap = argparse.ArgumentParser()
ap.add_argument("--db", type=Path, default=None)
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()
db = args.db or database_path()

with connect(db) as con:
    rows = [dict(r) for r in con.execute(
        "SELECT id, login, name, hotel FROM customer_accounts ORDER BY created_at")]

print(f"库: {db}")
print(f"客户账号 {len(rows)} 个")
print()

pending = []
for row in rows:
    existing = tenants.tenant_of_login(db, row["login"])
    if existing:
        print(f"  已有租户  {row['login']:20s} → {existing}")
        continue
    tenant = tenants.tenant_id_for_account(row["id"])
    pending.append((row, tenant))
    print(f"  待创建    {row['login']:20s} → {tenant}  ({(row.get('hotel') or row.get('name') or '')[:20]})")

print()
print(f"需要创建 {len(pending)} 个租户")

if not args.apply:
    print()
    print("  DRY RUN：未写入。加 --apply 执行")
    sys.exit(0)

print()
print("=== 写入 ===")
ok = fail = 0
for row, _tenant in pending:
    try:
        tenant = tenants.ensure_tenant_for_account(db, row)
        print(f"  ✓ {row['login']:20s} → {tenant}")
        ok += 1
    except Exception as exc:
        print(f"  ✗ {row['login']:20s} {type(exc).__name__}: {exc}")
        fail += 1

print()
print(f"  创建 {ok}，失败 {fail}")
with connect(db) as con:
    print(f"  tenants: {con.execute('SELECT COUNT(*) FROM tenants').fetchone()[0]}")
    print(f"  tenant_members: {con.execute('SELECT COUNT(*) FROM tenant_members').fetchone()[0]}")
    print(f"  accounts: {con.execute('SELECT COUNT(*) FROM customer_accounts').fetchone()[0]}")
    print(f"  integrity: {con.execute('PRAGMA integrity_check').fetchone()[0]}")
