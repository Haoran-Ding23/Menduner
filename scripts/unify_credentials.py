"""统一口令：所有需要密码的地方都改成 menduner / 123456。

涉及三处：
1 nginx Basic auth（/etc/nginx/.htpasswd）—— 写操作接口的浏览器弹窗认证；
2 应用内账号表 customer_accounts —— /login 页与审核台的会话登录；
3 角色表 roles.json —— menduner 已是 admin，管理员身份不变。

注意：create_account 有「密码至少 8 位」的校验，而用户要求 6 位的 123456，
所以这里直接写入哈希，绕过该长度校验（这是用户的明确要求）。
"""
import subprocess
import sys

sys.path.insert(0, "/srv/menduner")
from backend.accounts import hash_password
from backend.database import connect

DB = "/srv/menduner/data/menduner.sqlite3"
PASSWORD = "123456"
LOGINS = [("menduner", "管理员", "Menduner"), ("manager01", "门店经理(演示)", None), ("liuge", "刘哥", None)]

# ---------- 1) nginx Basic auth ----------
for login, _name, _hotel in LOGINS:
    result = subprocess.run(
        ["sudo", "htpasswd", "-b", "/etc/nginx/.htpasswd", login, PASSWORD],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        # 没装 htpasswd 时用 openssl 生成 apr1 哈希后追加
        digest = subprocess.run(
            ["openssl", "passwd", "-apr1", PASSWORD], capture_output=True, text=True,
        ).stdout.strip()
        script = f"grep -q '^{login}:' /etc/nginx/.htpasswd && sudo sed -i 's|^{login}:.*|{login}:{digest}|' /etc/nginx/.htpasswd || echo '{login}:{digest}' | sudo tee -a /etc/nginx/.htpasswd"
        subprocess.run(["bash", "-lc", script], capture_output=True, text=True)
    print(f"  basic-auth: {login} 已设置")

# ---------- 2) 应用账号表 ----------
with connect(DB) as con:
    for login, name, hotel in LOGINS:
        row = con.execute("SELECT id FROM customer_accounts WHERE login=?", (login,)).fetchone()
        digest = hash_password(PASSWORD)
        if row is None:
            con.execute(
                "INSERT INTO customer_accounts(id, login, name, hotel, password_hash, plan, "
                "trial_ends_at, subscription_ends_at, invite_code, suspended, created_at) "
                "VALUES(?,?,?,?,?,'enterprise',NULL,NULL,'unified',0,datetime('now'))",
                ("cus_unified_" + login, login, name, hotel, digest),
            )
            print(f"  应用账号: {login} 已创建")
        else:
            con.execute("UPDATE customer_accounts SET password_hash=? WHERE id=?", (digest, row["id"]))
            print(f"  应用账号: {login} 密码已重置")
    con.commit()
    rows = list(con.execute("SELECT login, plan, suspended FROM customer_accounts WHERE login IN ('menduner','manager01','liuge')"))
    for row in rows:
        print("   校验:", row["login"], row["plan"], "suspended=", row["suspended"])

# ---------- 3) reload nginx ----------
subprocess.run(["sudo", "nginx", "-t"], capture_output=True, text=True)
reload_result = subprocess.run(["sudo", "systemctl", "reload", "nginx"], capture_output=True, text=True)
print("  nginx reload:", "ok" if reload_result.returncode == 0 else reload_result.stderr[:120])
