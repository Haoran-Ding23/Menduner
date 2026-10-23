"""读目录页分包的真实请求配置。"""
import re

import httpx

H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
BASE = "https://data.suzhou.gov.cn"

with httpx.Client(timeout=25, follow_redirects=True, headers=H) as client:
    js = client.get(BASE + "/assets/js/chunk-4cda9de8.e35dcbc6.js").text
    print(f"目录分包 {len(js)} 字节")

    print("--- baseURL / 环境变量 ---")
    for m in re.findall(r'baseURL\s*[:=]\s*["\']([^"\']+)["\']', js):
        print("  baseURL:", m)
    for m in re.findall(r'VUE_APP_[A-Z_]+', js):
        print("  env:", m)

    print("--- 请求调用 (.get/.post) ---")
    calls = set(re.findall(r'\.(?:get|post|put|delete)\s*\(\s*["\']([^"\']+)["\']', js))
    for c in sorted(calls)[:30]:
        print(f"  {c}")

    print("--- 含 catalog/api/data 的路径字符串 ---")
    paths = set(re.findall(r'["\'](/[a-zA-Z0-9_\-/]{3,80})["\']', js))
    for p in sorted(paths):
        if re.search(r'catalog|api|data|resource|search', p, re.I) and not p.startswith("/assets"):
            print(f"  {p}")

    print("--- http 主机 ---")
    for host in sorted(set(re.findall(r'https?://[A-Za-z0-9.\-]+', js)))[:10]:
        print(f"  {host}")
