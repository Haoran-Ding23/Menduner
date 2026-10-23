"""挖苏州市公共数据开放平台的 JSON 接口。

单页应用的数据一定走接口：先看首页引用了哪些 JS，再从 JS 里提接口前缀，最后试目录接口。
"""
import re

import httpx

H = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
}
BASE = "https://data.suzhou.gov.cn"

with httpx.Client(timeout=20, follow_redirects=True, headers=H) as client:
    home = client.get(BASE + "/")
    print(f"首页 HTTP {home.status_code}  {len(home.text)} 字节")

    scripts = re.findall(r'<script[^>]+src="([^"]+)"', home.text)
    print(f"外链 JS: {len(scripts)} 个")
    for s in scripts[:8]:
        print(f"  {s}")

    # 从首页内联脚本里找接口线索
    inline = " ".join(re.findall(r"<script[^>]*>(.*?)</script>", home.text, re.S))
    for pattern in (r'["\'](/[A-Za-z0-9_\-/]*(?:api|service|data)[A-Za-z0-9_\-/]*)["\']',
                    r'baseURL\s*[:=]\s*["\']([^"\']+)["\']',
                    r'https?://[A-Za-z0-9.\-]+(?:/api)?'):
        hits = sorted(set(re.findall(pattern, inline)))[:6]
        if hits:
            print(f"  内联线索 {pattern[:22]}: {hits}")

    # 抓主 JS 包找接口
    api_paths: set[str] = set()
    for src in scripts[:6]:
        url = src if src.startswith("http") else BASE + ("/" if not src.startswith("/") else "") + src.lstrip("/")
        try:
            js = client.get(url).text
        except Exception:
            continue
        found = re.findall(r'["\'](/[a-zA-Z0-9_\-/]*(?:api|catalog|dataset|open)[a-zA-Z0-9_\-/]*)["\']', js)
        api_paths |= {f for f in found if len(f) > 6}
        base = re.findall(r'baseURL\s*[:=]\s*["\']([^"\']+)["\']', js)
        if base:
            print(f"  {src.split('/')[-1][:24]} baseURL: {base[:2]}")
    print(f"JS 里的接口路径: {len(api_paths)}")
    for path in sorted(api_paths)[:14]:
        print(f"  {path}")

    # 试常见目录接口
    print()
    print("=== 试接口 ===")
    candidates = [
        "/api/catalog/list", "/api/catalog", "/api/dataSet/list", "/api/dataset/list",
        "/service/catalog/list", "/api/open/catalog/list", "/api/v1/catalog/list",
        "/api/data/catalog/list", "/api/resource/list", "/api/catalog/search?keyword=文化",
    ]
    for path in candidates:
        try:
            r = client.get(BASE + path)
            ctype = r.headers.get("content-type", "")
            body = r.text[:120].replace("\n", " ")
            print(f"  {path:38s} {r.status_code}  {ctype[:24]:24s} {body[:60]}")
        except Exception as exc:
            print(f"  {path:38s} 失败 {type(exc).__name__}")
