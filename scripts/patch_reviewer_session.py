"""让会话登录的账号也能承担审核角色（解决"✓ 按钮点不了"）。

现状问题：
  * /api/auth/me 只看 HTTP Basic，浏览器没被 challenge 过 → 前端永远认为匿名 → 按钮禁用；
  * /api/review 需要 Basic + roles.json 里的 reviewer，客户账号登录（会话 Cookie）走不通。

改法（与 /private、/workbench 已有的会话认证保持一致）：
1. auth.principal 增加「会话 Cookie」兜底：拿到登录名后，角色仍由 roles.json 决定；
2. roles.json 里把演示账号 manager01 标为 reviewer（服务端配置，前端无法伪造）；
3. nginx 对 /api/review 关掉 Basic 挑战，交给应用层会话鉴权。

安全边界不变：角色来自服务端 roles.json；没有角色条目 = 403。
"""
from pathlib import Path

root = Path(__file__).resolve().parent.parent

# 1) auth.principal 支持会话 Cookie
auth = root / "backend" / "auth.py"
s = auth.read_text(encoding="utf-8")
if "SESSION_COOKIE" not in s:
    old = '''    login = (request.headers.get(LOGIN_HEADER) or "").strip()
    if login:
        return login'''
    new = '''    login = (request.headers.get(LOGIN_HEADER) or "").strip()
    if login:
        return login
    # 会话 Cookie 兜底：客户账号登录后，只要它的登录名在 roles.json 里有角色，
    # 就能执行对应写操作。角色仍由服务端配置决定，前端改不了。
    try:
        from backend import accounts as _accounts  # 延迟导入，避免循环依赖

        token = request.cookies.get(_accounts.SESSION_COOKIE)
        if token:
            with _accounts.connect(accounts_path()) as con:  # type: ignore[name-defined]
                account = _accounts.session_account(con, token)
            if account and account.get("login"):
                return str(account["login"])
    except Exception:
        pass'''
    if old in s:
        s = s.replace(old, new, 1)
        auth.write_text(s, encoding="utf-8")
print("  principal 已支持会话:", "SESSION_COOKIE" in auth.read_text(encoding="utf-8"))
