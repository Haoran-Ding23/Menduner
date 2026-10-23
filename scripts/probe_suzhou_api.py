"""确定苏州开放平台网关前缀后，列出目录接口并试出真实数据接口。"""
import re

import httpx

H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
BASE = "https://data.suzhou.gov.cn"

with httpx.Client(timeout=25, follow_redirects=True, headers=H) as client:
    js = client.get(BASE + "/assets/js/chunk-770e284b.9c10ebcd.js").text
    print(f"50KB 分包: {len(js)} 字节")

    liwy = sorted(set(re.findall(r'["\'](/liwy/[a-zA-Z0-9_\-/]+)["\']', js)))
    print(f"  /liwy/ 路径: {len(liwy)}")
    for p in liwy[:30]:
        print(f"    {p}")

    devapi = sorted(set(re.findall(r'/liwy/dev-api/[a-zA-Z0-9_\-/]+', js)))
    print(f"  dev-api 路径: {len(devapi)}")
    for p in devapi[:30]:
        print(f"    {p}")

    print()
    print("=== 试目录接口（带网关前缀）===")
    probes = [
        "/liwy/dev-api/data-open/catalog/page",
        "/liwy/dev-api/catalog/page",
        "/liwy/dev-api/data-open/resource/page",
        "/liwy/dev-api/data-open/dataset/page",
        "/liwy/dev-api/data-open/catalog/list",
    ]
    for path in probes:
        for method in ("get", "post"):
            try:
                r = (client.get if method == "get" else client.post)(BASE + path)
                ctype = r.headers.get("content-type", "")
                body = r.text[:120].replace("\n", " ")
                print(f"  {method.upper():4s} {path:46s} {r.status_code}  {ctype[:24]:24s} {body[:50]}")
                if "json" in ctype or r.text.startswith("{"):
                    break
            except Exception as exc:
                print(f"  {method.upper():4s} {path:46s} 失败 {type(exc).__name__}")
