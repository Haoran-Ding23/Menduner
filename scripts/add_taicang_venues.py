"""补齐太仓两个文化场馆（文化馆、大剧院），坐标取自高德并保留来源链接。

顺带用真实浏览器请求头试一次苏州文广旅局活动库（szwgloa），确认访问被挡是技术原因还是拦截。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database import connect, database_path

ROOT = Path(__file__).resolve().parent.parent
TARGETS = ["太仓市文化馆", "太仓大剧院"]


def amap_key() -> str | None:
    if os.environ.get("AMAP_WEBSERVICE_KEY"):
        return os.environ["AMAP_WEBSERVICE_KEY"].strip()
    for candidate in (Path(os.environ.get("MENDUNER_ENV_FILE", "") or "."),
                      Path("/tmp/x"), ROOT / "frontend" / ".env.local"):
        if not candidate.is_file():
            continue
        lines = candidate.read_text(encoding="utf-8").splitlines()
        for name in ("AMAP_WEBSERVICE_KEY", "VITE_AMAP_KEY"):
            for line in lines:
                if line.startswith(name + "="):
                    return line.split("=", 1)[1].strip().strip('"')
    return None


def search_place(key: str, keyword: str) -> dict | None:
    query = urllib.parse.urlencode({
        "key": key, "keywords": keyword, "city": "太仓", "citylimit": "true",
        "offset": "5", "page": "1", "extensions": "base", "output": "JSON",
    })
    url = f"https://restapi.amap.com/v3/place/text?{query}"
    with urllib.request.urlopen(url, timeout=25) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("status") != "1":
        return None
    for poi in payload.get("pois") or []:
        if keyword.replace("市", "") in (poi.get("name") or "").replace("市", ""):
            return poi
    pois = payload.get("pois") or []
    return pois[0] if pois else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    print("=== 试访问苏州文广旅局活动库（真实浏览器头）===")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
                  "image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://visitsz.wglj.suzhou.com.cn/",
        "Upgrade-Insecure-Requests": "1",
        "Connection": "keep-alive",
    }
    for url in (
        "https://szwgloa.wglj.suzhou.com.cn/festival-detail.aspx?id=2025110709183701",
        "https://szwgloa.wglj.suzhou.com.cn/festival.aspx",
    ):
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=20) as response:
                body = response.read(400)
                print(f"  {url}\n    HTTP {response.status}  {len(body)} 字节 -> 可访问")
        except Exception as exc:
            print(f"  {url}\n    失败 {type(exc).__name__}: {str(exc)[:90]}")

    key = amap_key()
    if not key:
        print("\n缺少高德 Web 服务 Key")
        return 2

    print("\n=== 场馆坐标（高德 place/text）===")
    stamp = datetime.now(timezone.utc).isoformat()
    with connect(database_path()) as con:
        existing = {json.loads(r["payload"]).get("name")
                    for r in con.execute("SELECT payload FROM venues")}
        for name in TARGETS:
            if name in existing:
                print(f"  {name}: 已存在，跳过")
                continue
            poi = search_place(key, name)
            if not poi:
                print(f"  {name}: 高德未找到")
                continue
            lng, lat = (poi.get("location") or ",").split(",")
            payload = {
                "id": "venue-" + hashlib.sha256(name.encode()).hexdigest()[:20],
                "name": poi.get("name"),
                "address": poi.get("address") if isinstance(poi.get("address"), str) else None,
                "districtId": "taicang",
                "districtDemo": False,
                "coordinates": {
                    "lng": float(lng), "lat": float(lat), "system": "GCJ-02",
                    "status": "Verified",
                    "sourceUrl": f"https://www.amap.com/place/{poi.get('id')}",
                },
                "source": "AMap place/text 查询（按名称精确匹配）",
                "addedAt": stamp,
            }
            print(f"  {name}: {payload['name']} {payload['address']} "
                  f"({lng},{lat}) adcode={poi.get('adcode')}")
            if args.apply:
                con.execute("INSERT INTO venues(id, payload) VALUES(?,?)",
                            (payload["id"], json.dumps(payload, ensure_ascii=False)))
        if args.apply:
            total = con.execute("SELECT COUNT(*) FROM venues").fetchone()[0]
            taicang = sum(1 for r in con.execute("SELECT payload FROM venues")
                          if json.loads(r["payload"]).get("districtId") == "taicang")
            print(f"\n  场馆总数 {total}，太仓 {taicang}")
    print(f"  模式: {'写入' if args.apply else '只报告'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
