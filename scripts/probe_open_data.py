"""探针：太仓文化体育栏目、政府站 RSS、苏州公共数据开放平台。"""
import re

import httpx

H = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
}
C = httpx.Client(timeout=25, follow_redirects=True, headers=H)


def visible(html: str) -> str:
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", " ", t).replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", t).strip()


def probe(label: str, url: str, want_detail: bool = False) -> None:
    print(f"--- {label}: {url}")
    try:
        r = C.get(url)
        ctype = r.headers.get("content-type", "")
        print(f"    HTTP {r.status_code}  {len(r.content)} 字节  {ctype[:40]}")
        if r.status_code != 200:
            return
        if "xml" in ctype or url.endswith((".xml", ".rss")):
            print(f"    XML 头部: {r.text[:180].replace(chr(10), ' ')}")
            return
        articles = re.findall(r"/taicang/([a-z]+)/(20\d{4})/([0-9a-f]{20,})\.shtml", r.text)
        uniq = list(dict.fromkeys(articles))
        print(f"    文章链接: {len(uniq)}  栏目: {sorted({a[0] for a in uniq})}")
        titles = re.findall(r'href="(/taicang/[a-z]+/20\d{4}/[0-9a-f]{20,}\.shtml)"[^>]*>(.*?)</a>',
                            r.text, re.S)
        seen = set()
        for href, raw in titles[:4]:
            title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", raw)).strip()
            if title and title not in seen:
                seen.add(title)
                print(f"      · {title[:46]}")
        if want_detail and uniq:
            href = f"/taicang/{uniq[0][0]}/{uniq[0][1]}/{uniq[0][2]}.shtml"
            detail = C.get("http://www.taicang.gov.cn" + href)
            text = visible(detail.text)
            fields = re.findall(r"(活动时间|活动日期|展览时间|展览日期|演出时间|时间)[:：]\s*([^ ]{4,40})", text)
            print(f"      详情字段: {fields[:3] or '无标注日期字段'}")
    except Exception as exc:
        print(f"    失败 {type(exc).__name__}: {str(exc)[:70]}")


BASE = "http://www.taicang.gov.cn"
probe("太仓 文化体育政策 列表1", BASE + "/taicang/whtyzc/zdzwxx_list.shtml", want_detail=True)
probe("太仓 文化体育政策 列表2", BASE + "/taicang/whtyzc/zdzwxx_list_2.shtml")
probe("太仓 广场文艺", BASE + "/taicang/whtyzc/zwfw_list.shtml")
print()
print("=== RSS 候选 ===")
for path in ("/taicang/rss.xml", "/rss.xml", "/rss/", "/taicang/xwzx/rss.shtml",
             "/taicang/whtyzc/rss.shtml", "/sitemap.xml"):
    probe("RSS " + path, BASE + path)
print()
print("=== 苏州公共数据开放平台 ===")
for url in ("http://data.suzhou.gov.cn/", "https://data.suzhou.gov.cn/",
            "http://opendata.suzhou.gov.cn/", "http://data.taicang.gov.cn/"):
    try:
        r = C.get(url)
        text = visible(r.text)[:120]
        print(f"  {url} -> HTTP {r.status_code}  {len(r.content)} 字节  {text[:70]}")
    except Exception as exc:
        print(f"  {url} -> 失败 {type(exc).__name__}")
