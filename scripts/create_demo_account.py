"""在生产上创建并验证演示账号。

演示账号要能被页面上写的那两个值真正登录，所以走完整注册链路（邀请码 → 注册 → 自动建租户），
再上传一份**合成**的经营数据，让「本店经营数据」和「导出周报」不是空的。

数据是示例，不来自任何真实酒店；租户名里写明「示例数据」，周报也会带这个名字。
"""
import sys
from datetime import date
from pathlib import Path

import httpx

sys.path.insert(0, "/srv/menduner")

from backend import accounts, weekly_report
from backend.database import connect, database_path

BASE = "http://127.0.0.1/api"
LOGIN = "manager01"
PASSWORD = "hotel2026"
NAME = "演示账号"
HOTEL = "演示酒店（示例数据）"

db = database_path()
client = httpx.Client(base_url=BASE, timeout=60)

print("=== 0. 已存在？ ===")
with connect(db) as con:
    row = con.execute("SELECT id, login FROM customer_accounts WHERE login=?", (LOGIN,)).fetchone()
print(f"  {dict(row) if row else None}")

if row is None:
    print("=== 1. 创建邀请码 ===")
    with connect(db) as con:
        invite = accounts.create_invite(
            con, plan="pro", trial_days=365, max_uses=1, note="公开演示账号",
            created_by="demo", expires_in_days=None,
        )
    print(f"  {invite['code']}")

    print("=== 2. 注册演示账号 ===")
    r = client.post("/account/register", json={
        "invite_code": invite["code"], "login": LOGIN, "password": PASSWORD,
        "name": NAME, "hotel": HOTEL,
    })
    print(f"  HTTP {r.status_code}  {str(r.json())[:120] if r.status_code != 200 else 'ok'}")
else:
    print("  账号已存在，跳过注册")

print("=== 3. 登录验证 ===")
r = client.post("/account/login", json={"login": LOGIN, "password": PASSWORD})
print(f"  HTTP {r.status_code}")
if r.status_code != 200:
    print(f"  失败：{r.text[:200]}")
    sys.exit(1)

print("=== 4. 上传示例经营数据 ===")
# 上一完整周的工作日，合成数值。
start, end = weekly_report.week_range(date.today())
lines = ["日期,出租率(%),平均房价(%),间夜"]
samples = [
    (0, 62.5, 486, 92), (1, 58.0, 468, 86), (2, 64.0, 492, 95),
    (3, 71.5, 520, 104), (4, 86.0, 610, 126), (5, 92.5, 658, 134), (6, 74.0, 540, 108),
]
for offset, occ, adr, nights in samples:
    day = date.fromordinal(start.toordinal() + offset)
    lines.append(f"{day.isoformat()},{occ},{adr},{nights}")
csv = ("\n".join(lines) + "\n").encode()
r = client.post("/private/import?filename=demo-week.csv&apply=1", content=csv)
print(f"  HTTP {r.status_code}  written={r.json().get('written') if r.status_code == 200 else r.text[:160]}")

print("=== 5. 读回本店数据 ===")
r = client.get("/private/metrics")
data = r.json() if r.status_code == 200 else {}
print(f"  HTTP {r.status_code}  tenant={data.get('tenant')}  count={data.get('count')}")

print("=== 6. 周报可用性 ===")
for fmt in ("xlsx", "pdf"):
    r = client.get(f"/private/weekly.{fmt}")
    print(f"  weekly.{fmt} -> {r.status_code}  {len(r.content)} bytes  {r.content[:5]!r}")

print("=== 7. 租户与成员 ===")
r = client.get("/tenant/members")
print(f"  HTTP {r.status_code}  {str(r.json())[:200] if r.status_code == 200 else ''}")
