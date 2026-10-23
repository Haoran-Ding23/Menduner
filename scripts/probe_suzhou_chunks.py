"""定位苏州开放平台按需加载的分包，找出真正的数据接口。"""
import re

import httpx

H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
BASE = "https://data.suzhou.gov.cn"

with httpx.Client(timeout=25, follow_redirects=True, headers=H) as client:
    index = client.get(BASE + "/assets/js/index.87b2156a.js").text

    # 分包文件名映射（webpack 的 chunk 名）
    chunks = sorted(set(re.findall(r'assets/js/[A-Za-z0-9_\-./]+\.js', index)))
    print(f"主包引用的分包: {len(chunks)}")
    for c in chunks[:20]:
        print(f"  {c}")

    # 找分包名到哈希的映射：通常形如 "catalog": "xxxx"
    mapping = re.findall(r'["\']([a-zA-Z0-9\-_]+)["\']\s*:\s*["\']([0-9a-f]{8})["\']', index)
    print(f"  路由->哈希映射: {mapping[:12]}")

    print()
    print("=== 逐个分包找接口请求 ===")
    seen: set[str] = set()
    candidates: set[str] = set()
    for chunk in chunks:
        if chunk in seen:
            continue
        seen.add(chunk)
        try:
            js = client.get(BASE + "/" + chunk).text
        except Exception:
            continue
        urls = set(re.findall(r'["\'](/[a-zA-Z0-9_\-/]{3,70})["\']', js))
        hits = {u for u in urls
                if re.search(r'api|catalog|dataset|resource|data|search|gateway|open', u, re.I)
                and not u.startswith(("/assets", "/catalog/", "/openStatistics"))}
        if hits:
            print(f"  {chunk.split('/')[-1]}:")
            for h in sorted(hits)[:10]:
                print(f"      {h}")
                candidates.add(h)
        # 请求方法包裹的
        for m in re.findall(r'\.(?:get|post|put)\s*\(\s*["\'](/[^"\']+)["\']', js):
            if re.search(r'api|catalog|data|search', m, re.I):
                candidates.add(m)
                print(f"      (call) {m}")

    print()
    print("=== 汇总候选接口 ===")
    for c in sorted(candidates)[:20]:
        print(f"  {c}")
