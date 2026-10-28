"""把统一账号 menduner 设成有效付费套餐（否则付费页面被锁）。

用户要求：账号 menduner / 密码 123456 能登录并使用全部功能。
账号已建，但套餐被判定为 free/expired —— 付费页（本店经营数据、商圈洞察）会被挡住。
这里设置 plan=enterprise 且订阅到期日设到远期。
"""
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/srv/menduner")
from backend.database import connect

DB = "/srv/menduner/data/menduner.sqlite3"
FAR = (datetime.now(timezone.utc) + timedelta(days=3650)).isoformat(timespec="seconds")

with connect(DB) as con:
    for login in ("menduner", "manager01", "liuge"):
        con.execute(
            "UPDATE customer_accounts SET plan='enterprise', subscription_ends_at=?, "
            "trial_ends_at=NULL, suspended=0 WHERE login=?",
            (FAR, login),
        )
    con.commit()
    for row in con.execute(
        "SELECT login, plan, subscription_ends_at, suspended FROM customer_accounts "
        "WHERE login IN ('menduner','manager01','liuge')"
    ):
        print(f"  {row['login']}: plan={row['plan']} 到期={row['subscription_ends_at']} 停用={row['suspended']}")
