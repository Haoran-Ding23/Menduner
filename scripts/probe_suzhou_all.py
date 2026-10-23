"""枚举苏州开放平台全部分包，定位目录接口与请求方式。"""
import re

import httpx

H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
BASE = "https://data.suzhou.gov.cn"

with httpx.Client(timeout=25, follow_redirects=True, headers=H) as client:
    index = client.get(BASE + "/assets/js/index.87b2156a.js").text
    pairs = re.findall(r'["\'](chunk-[0-9a-f]+)["\']\s*:\s*["\']([0-9a-f]{8})["\']', index)
    print(f"分包映射 {len(pairs)} 条")

    devapi: set[str] = set()
    catalog_chunks: dict[str, list[str]] = {}
    for name, hash_suffix in pairs:
        filename = f"assets/js/{name}.{hash_suffix}.js"
        try:
            js = client.get(BASE + "/" + filename).text
        except Exception:
            continue
        # 数据接口路径
        for p in set(re.findall(r'["\'](/liwy/dev-api/[a-zA-Z0-9_\-/]+)["\']', js)):
            devapi.add(p)
        # 目录/数据集关键词（页面标题、栏目标签）
        words = [w for w in ("数据目录", "资源目录", "数据集", "数据资源", "目录检索")
                 if w in js]
        if words:
            catalog_chunks.setdefault(filename.split("/")[-1], words)

    print(f"dev-api 接口路径: {len(devapi)}")
    for p in sorted(devapi)[:40]:
        print(f"    {p}")

    print(f"\n含目录关键词的分包: {len(catalog_chunks)}")
    for chunk, words in catalog_chunks.items():
        print(f"    {chunk}  关键词={words}")

    print("\n=== 试目录接口 ===")
    probes = [p for p in devapi if re.search(r"catalog|resource|data-open", p, re.I)]
    for path in probes[:10]:
        try:
            r = client.post(BASE + path, json={"pageNum": 1, "pageSize": 5, "keyword": "文化"})
            ctype = r.headers.get("content-type", "")
            body = r.text[:100].replace("\n", " ")
            print(f"  POST {path:52s} {r.status_code}  {ctype[:22]:22s} {body[:60]}")
        except Exception as exc:
            print(f"  POST {path:52s} 失败 {type(exc).__name__}")
