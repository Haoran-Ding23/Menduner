"""一次探完：苏州/太仓数据开放平台是否可用，以及「文化体育政策」栏目的日期是发布还是活动时间。"""
import re

import httpx

H = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def visible(html: str) -> str:
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", " ", t).replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", t).strip()


def get(url: str):
    try:
        with httpx.Client(timeout=12, follow_redirects=True, headers=H) as client:
            return client.get(url)
    except Exception as exc:
        return exc


print("=== 1. 数据开放平台候选 ===")
CANDIDATES = [
    "https://data.suzhou.gov.cn/",
    "http://data.suzhou.gov.cn/",
    "https://opendata.suzhou.gov.cn/",
    "https://data.taicang.gov.cn/",
    "https://www.suzhou.gov.cn/szsrmzf/sjkf/sjkf.shtml",
    "http://www.taicang.gov.cn/taicang/dataopen/sjkf.shtml",
]
for url in CANDIDATES:
    result = get(url)
    if isinstance(result, Exception):
        print(f"  {url:58s} 失败 {type(result).__name__}")
        continue
    text = visible(result.text)
    title = re.search(r"<title>(.*?)</title>", result.text, re.S)
    print(f"  {url:58s} HTTP {result.status_code}  {len(result.content):7d} 字节  "
          f"title={ (title.group(1).strip()[:28] if title else '') }")
    if result.status_code == 200 and ("数据集" in text or "数据目录" in text or "开放" in text):
        for word in ("数据集", "接口", "API", "下载", "文化", "旅游"):
            if word in text:
                i = text.find(word)
                print(f"      {word}: …{text[max(0, i - 30):i + 40]}…")
                break

print()
print("=== 2. 「文化体育政策」日期字段判定 ===")
BASE = "http://www.taicang.gov.cn"
list_html = get(BASE + "/taicang/whtyzc/zdzwxx_list.shtml")
if isinstance(list_html, Exception):
    print("  列表页失败")
else:
    links = re.findall(r'href="(/taicang/whtyzc/20\d{4}/[0-9a-f]{20,}\.shtml)"[^>]*>(.*?)</a>',
                       list_html.text, re.S)
    print(f"  文章: {len(links)} 篇")
    for href, raw in links[:3]:
        title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", raw)).strip()
        detail = get(BASE + href)
        if isinstance(detail, Exception):
            print(f"    {title[:30]} 失败")
            continue
        text = visible(detail.text)
        # 发布时间 vs 活动时间：看是否有「活动时间/日期」标注，以及正文里时间条的出现位置
        labelled = re.findall(r"(活动时间|活动日期|举办时间|展览时间|展期|演出时间)[:：]\s*([^ ]{4,30})", text)
        publish = re.findall(r"(发布时间|来源：|时间：)\s*[:：]?\s*(20\d{2}[-/年.]\d{1,2}[-/月.]\d{1,2})", text)
        dates = re.findall(r"20\d{2}[-年.]\d{1,2}[-月.]\d{1,2}", text)
        print(f"    {title[:34]}")
        print(f"      标注活动时间: {labelled[:2] or '无'}   发布类: {publish[:2] or '无'}")
        print(f"      正文日期数: {len(dates)}  前 3 个: {dates[:3]}")

print()
print("=== 3. 太仓数据开放栏目 ===")
r = get(BASE + "/taicang/dataopen/sjkf.shtml")
if isinstance(r, Exception):
    print(f"  失败 {type(r).__name__}")
else:
    text = visible(r.text)
    print(f"  HTTP {r.status_code}  {len(r.content)} 字节")
    for word in ("数据集", "接口", "下载", "目录", "开放"):
        if word in text:
            i = text.find(word)
            print(f"    {word}: …{text[max(0, i - 40):i + 50]}…")
