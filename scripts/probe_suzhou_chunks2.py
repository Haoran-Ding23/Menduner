"""用 chunk 名->哈希映射拼出真实分包文件名，从中找数据接口。"""
import re

import httpx

H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
BASE = "https://data.suzhou.gov.cn"

with httpx.Client(timeout=25, follow_redirects=True, headers=H) as client:
    index = client.get(BASE + "/assets/js/index.87b2156a.js").text
    pairs = re.findall(r'["\'](chunk-[0-9a-f]+)["\']\s*:\s*["\']([0-9a-f]{8})["\']', index)
    print(f"映射 {len(pairs)} 条")

    candidates: dict[str, set[str]] = {}
    for name, hash_suffix in pairs[:14]:
        filename = f"assets/js/{name}.{hash_suffix}.js"
        try:
            js = client.get(BASE + "/" + filename).text
        except Exception as exc:
            print(f"  {filename} 失败 {type(exc).__name__}")
            continue
        print(f"  {filename.split('/')[-1]:34s} {len(js):7d} 字节")

        # 请求地址、baseURL、http 主机
        urls = set(re.findall(r'["\'](/[a-zA-Z0-9_\-/]{3,80})["\']', js))
        hits = {u for u in urls
                if re.search(r'api|catalog|dataset|resource|data|search|gateway|open|service', u, re.I)}
        if hits:
            candidates[filename.split('/')[-1]] = hits
        for m in re.findall(r'\.(?:get|post|put)\s*\(\s*["\']([^"\']+)["\']', js):
            candidates.setdefault(filename.split('/')[-1], set()).add("(call) " + m)

    print()
    print("=== 命中接口的分包 ===")
    for chunk, urls in candidates.items():
        print(f"  {chunk}:")
        for u in sorted(urls)[:8]:
            print(f"      {u}")
