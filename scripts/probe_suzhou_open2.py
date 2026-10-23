"""挖苏州开放平台的真实 API 前缀：从 Vue bundle 里找请求配置。"""
import re

import httpx

H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
BASE = "https://data.suzhou.gov.cn"

with httpx.Client(timeout=25, follow_redirects=True, headers=H) as client:
    bundles = ["assets/js/index.87b2156a.js", "assets/js/chunk-common.e391e92a.js"]
    for bundle in bundles:
        js = client.get(BASE + "/" + bundle).text
        print(f"=== {bundle}  {len(js)} 字节 ===")

        # baseURL / 网关前缀
        for m in re.findall(r'baseURL\s*[:=]\s*["\']([^"\']+)["\']', js):
            print(f"  baseURL: {m}")

        # 明确的 http(s) 请求目标
        hosts = sorted(set(re.findall(r'https?://[A-Za-z0-9.\-]+', js)))
        print(f"  http 主机: {hosts[:8]}")

        # 请求路径字符串：axios.get('/x'), url:'/x', '/x' 形式的接口
        paths = set()
        paths |= set(re.findall(r'\.(?:get|post|put)\s*\(\s*["\'](/[^"\']+)["\']', js))
        paths |= set(re.findall(r'url\s*:\s*["\'](/[^"\']+)["\']', js))
        paths |= set(re.findall(r'["\'](/[a-zA-Z0-9_\-/]{2,60})["\']\s*[,)]', js))
        # 过滤掉明显是前端资源/路由的
        keep = [p for p in sorted(paths)
                if not p.startswith(("/assets", "/catalog", "/openStatistics", "/img", "/static"))
                and p != "/"]
        print(f"  接口候选路径: {len(keep)}")
        for p in keep[:20]:
            print(f"    {p}")

    print()
    print("=== 直接试带关键字的数据集接口 ===")
    for path in (
        "/gateway/catalog/list", "/gateway/api/catalog/list", "/api/gateway/catalog/list",
        "/openapi/catalog/list", "/szdsj/catalog/list", "/catalog/api/list",
        "/api/catalog/page", "/api/data/page",
    ):
        try:
            r = client.get(BASE + path)
            print(f"  {path:40s} {r.status_code}  {r.headers.get('content-type','')[:24]:24s} {r.text[:50].replace(chr(10),' ')}")
        except Exception as exc:
            print(f"  {path:40s} 失败 {type(exc).__name__}")
