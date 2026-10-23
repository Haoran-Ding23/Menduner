"""补齐剩下几条没有地区的社交事件。

优先级：生产库里该场馆已有核验坐标 → 逆地理编码；否则按场馆名查高德（带重试）；
最后才用 AI 读出的地点文字，且只到市级。
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ADNAME_TO_SLUG = {
    "太仓市": "taicang", "昆山市": "kunshan", "常熟市": "changshu", "张家港市": "zhangjiagang",
    "姑苏区": "gusu", "虎丘区": "huqiu", "吴中区": "wuzhong", "相城区": "xiangcheng",
    "吴江区": "wujiang", "工业园区": "wuzhong", "苏州工业园区": "wuzhong",
}


def amap_key() -> str | None:
    if os.environ.get("AMAP_WEBSERVICE_KEY"):
        return os.environ["AMAP_WEBSERVICE_KEY"].strip()
    for candidate in (Path(os.environ.get("MENDUNER_ENV_FILE", "") or "."),
                      ROOT / "frontend" / ".env.local"):
        if not candidate.is_file():
            continue
        lines = candidate.read_text(encoding="utf-8").splitlines()
        for name in ("AMAP_WEBSERVICE_KEY", "VITE_AMAP_KEY"):
            for line in lines:
                if line.startswith(name + "="):
                    return line.split("=", 1)[1].strip().strip('"')
    return None


def call(url: str, attempts: int = 3) -> dict | None:
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if payload.get("status") == "1":
                return payload
        except Exception:
            pass
        time.sleep(1.5 * (attempt + 1))
    return None


def regeo(key: str, lng: float, lat: float) -> dict | None:
    url = "https://restapi.amap.com/v3/geocode/regeo?" + urllib.parse.urlencode(
        {"key": key, "location": f"{lng:.6f},{lat:.6f}", "extensions": "base", "output": "JSON"})
    payload = call(url)
    if not payload:
        return None
    component = (payload.get("regeocode") or {}).get("addressComponent") or {}
    return {"adname": component.get("district") or "", "adcode": str(component.get("adcode") or ""),
            "how": "场馆坐标逆地理编码"}


def by_name(key: str, name: str) -> dict | None:
    for city in ("苏州", ""):
        query = {"key": key, "keywords": name, "offset": "5", "extensions": "base", "output": "JSON"}
        if city:
            query["city"] = city
            query["citylimit"] = "true"
        payload = call("https://restapi.amap.com/v3/place/text?" + urllib.parse.urlencode(query))
        if not payload:
            continue
        for poi in payload.get("pois") or []:
            adcode = str(poi.get("adcode") or "")
            if city and not adcode.startswith("3205"):
                continue
            return {"adname": poi.get("adname") or "", "adcode": adcode,
                    "how": f"场馆名高德查询（{poi.get('name')}）"}
    return None


def main() -> int:
    apply = "--apply" in sys.argv
    key = amap_key()
    if not key:
        print("缺少高德 Web 服务 Key")
        return 2

    con = sqlite3.connect(os.environ["MENDUNER_DB_PATH"])
    con.row_factory = sqlite3.Row
    venues = {r["id"]: json.loads(r["payload"]) for r in con.execute("SELECT id,payload FROM venues")}
    rows = list(con.execute(
        "SELECT id,name,venue,payload FROM events WHERE source='xiaohongshu-note-import' "
        "AND district IS NULL"))

    for row in rows:
        payload = json.loads(row["payload"])
        venue = venues.get(row["venue"] or "") or {}
        coords = venue.get("coordinates") or {}
        info = None
        if coords.get("lng") is not None:
            info = regeo(key, coords["lng"], coords["lat"])
        if info is None and payload.get("venueName"):
            info = by_name(key, payload["venueName"])

        slug = ADNAME_TO_SLUG.get((info or {}).get("adname", ""))
        evidence = None
        if slug:
            evidence = f"{info['how']}：{info['adname']}（adcode {info['adcode']}）"
        else:
            location = (payload.get("location") or "").strip()
            if "太仓" in location:
                slug, evidence = "taicang", f"AI 读出的地点「{location}」，未定位到场馆"
            elif "苏州" in location or "姑苏" in location:
                slug, evidence = "suzhou", f"AI 读出的地点「{location}」，只到市级"

        print(f"  {row['name'][:32]:32s} → {slug or '仍未确定'}  {evidence or ''}")
        if slug and apply:
            payload["districtId"] = slug
            payload["districtEvidence"] = evidence
            con.execute("UPDATE events SET district=?, payload=? WHERE id=?",
                        (slug, json.dumps(payload, ensure_ascii=False), row["id"]))
    if apply:
        con.commit()
        left = con.execute(
            "SELECT COUNT(*) FROM events WHERE source='xiaohongshu-note-import' AND district IS NULL"
        ).fetchone()[0]
        print(f"  仍无地区: {left}")
    print(f"  模式: {'写入' if apply else '只报告'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
