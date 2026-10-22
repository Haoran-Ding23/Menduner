"""给 nginx 增加 /api/tenant/ 位置块。

成员接口是 POST/DELETE，而 nginx 按方法鉴权：GET 免 Basic、其余要 Basic。客户没有运维
账号，所以这两条也必须走会话鉴权；后端在没有会话时仍然返回 401。
"""
import pathlib
import subprocess

path = pathlib.Path("/etc/nginx/snippets/menduner-app.conf")
text = path.read_text(encoding="utf-8")
if "location /api/tenant/" in text:
    print("  nginx: /api/tenant/ 已存在")
else:
    block = """    # Member management authenticates with the session cookie, like the private ledger:
    # customers do not hold operator credentials. The backend still answers 401 without a
    # session, so this is not an open path.
    location /api/tenant/ {
        auth_basic off;

        proxy_pass http://127.0.0.1:8000/tenant/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

"""
    marker = "    location /api/ {"
    index = text.index(marker)
    path.write_text(text[:index] + block + text[index:], encoding="utf-8")
    print("  nginx: /api/tenant/ 已插入")

result = subprocess.run(["nginx", "-t"], capture_output=True, text=True)
print("  nginx -t:", (result.stderr or result.stdout).strip().splitlines()[-1])
if result.returncode == 0:
    subprocess.run(["systemctl", "reload", "nginx"], check=True)
    print("  nginx reloaded")
