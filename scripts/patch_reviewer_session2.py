"""让会话登录的账号也能承担审核角色（解决“✓ 按钮点不了”）。

现状：/api/auth/me 只看 HTTP Basic，浏览器没被 challenge → 前端永远认为匿名 → 按钮禁用；
      /api/review 需要 Basic + roles.json 的 reviewer，客户账号会话走不通。

改法（与 /private、/workbench 已有的会话认证一致）：
1. auth.principal 增加会话 Cookie 兜底，角色仍由服务端 roles.json 决定；
2. nginx 对 /api/review 关掉 Basic 挑战，交给应用层会话鉴权（在部署脚本里做）。
"""
from pathlib import Path

root = Path(__file__).resolve().parent.parent
auth = root / "backend" / "auth.py"
s = auth.read_text(encoding="utf-8")

if "SESSION_COOKIE" not in s:
    old = '''    login = (request.headers.get(LOGIN_HEADER) or "").strip()
    if login:
        return login'''
    new = '''    login = (request.headers.get(LOGIN_HEADER) or "").strip()
    if login:
        return login
    # 会话 Cookie 兜底：客户账号登录后，只要登录名在 roles.json 里有角色，就能执行写操作。
    # 角色仍来自服务端配置，前端无法伪造。
    try:
        from backend import accounts as _accounts
        from backend.database import connect as _connect, database_path as _database_path

        token = request.cookies.get(_accounts.SESSION_COOKIE)
        if token:
            with _connect(_database_path()) as con:
                account = _accounts.session_account(con, token)
            if account and account.get("login"):
                return str(account["login"])
    except Exception:
        pass'''
    if old in s:
        s = s.replace(old, new, 1)
        auth.write_text(s, encoding="utf-8")

print("  principal 支持会话:", "SESSION_COOKIE" in auth.read_text(encoding="utf-8"))
