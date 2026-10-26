"""商圈洞察五项验收（GPT Round 19 指定）。只做只读检查，不修改任何数据。

用法（在能访问后端的机器上）：
  python scripts/verify_market_acceptance.py http://127.0.0.1:8000
输出每一项的通过/失败与实测值，可直接贴进验收报告。
"""
from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
results: list[tuple[str, bool, str]] = []


def get(path: str):
    started = time.time()
    with urllib.request.urlopen(BASE + path, timeout=60) as response:
        payload = json.loads(response.read().decode())
    return payload, round(time.time() - started, 3)


def check(name: str, ok: bool, detail: str) -> None:
    results.append((name, ok, detail))


# ① 酒店数据质量
areas, _ = get("/market/areas?radius=800")
dataset, dataset_seconds = get("/dataset")
hotels = dataset["hotels"]
poi_ids = [h["id"] for h in hotels]
with_coords = [h for h in hotels
               if (h.get("coordinates") or {}).get("lng") is not None]
bad_coord = [h for h in hotels if (h.get("coordinates") or {}).get("system") not in (None, "GCJ-02")]
check("① 住宿设施数据质量",
      len(poi_ids) == len(set(poi_ids)) and len(with_coords) >= 400 and not bad_coord,
      f"共 {len(hotels)} 条，去重后 {len(set(poi_ids))}，有坐标 {len(with_coords)}，"
      f"坐标系异常 {len(bad_coord)}")

# ② 空间统计正确：观前分层之和 = 该中心酒店数
guangqian = next((a for a in areas["areas"] if a["name"] == "观前"), areas["areas"][0])
profile, _ = get("/market/area/" + urllib.parse.quote(guangqian["id"]) + "?radius=800")
bands = profile["hotelDistribution"]["bands"]
band_sum = sum(band["count"] for band in bands)
check("② 空间统计正确",
      band_sum == profile["hotelDistribution"]["count"] == len(profile["hotelCalendar"]),
      f"{guangqian['name']} 酒店 {profile['hotelDistribution']['count']} 家，"
      f"分层 {[b['count'] for b in bands]} 合计 {band_sum}")

# ③ 图表真实可读：关键序列来自接口且非空
weekly = profile.get("weekly", [])
check("③ 图表数据驱动",
      bool(profile.get("categories")) or bool(weekly),
      f"类别 {len(profile.get('categories', []))} 组，周度 {len(weekly)} 个点，"
      f"Top10 {len(areas['areas'])} 个中心可取")

# ④ 服务与响应：主接口耗时
coverage, coverage_seconds = get("/market/coverage?radius=800")
check("④ 接口响应",
      coverage_seconds < 3 and dataset_seconds < 5,
      f"coverage {coverage_seconds}s、dataset {dataset_seconds}s（{round(len(json.dumps(dataset))/1e6,1)} MB）")

# ⑤ 数据一致：活动口径不变，且三者相加等于分母
total = coverage["identitiesTotal"]
parts = coverage["eventsNearby"] + coverage["eventsAmbiguous"] + coverage["eventsUnmatched"]
official = coverage["officialCount"]
candidate = coverage["candidateCount"]
check("⑤ 口径一致性",
      parts == total and official + candidate == coverage["areaCount"],
      f"分母 {total} = 唯一 {coverage['eventsNearby']} + 歧义 {coverage['eventsAmbiguous']} "
      f"+ 未匹配 {coverage['eventsUnmatched']}；官方 {official} + 候选 {candidate} = {coverage['areaCount']}")

print()
for name, ok, detail in results:
    print(("  [PASS] " if ok else "  [FAIL] ") + name + " — " + detail)
passed = sum(1 for _, ok, _ in results if ok)
print(f"\n  五项验收：{passed}/{len(results)} 通过")
sys.exit(0 if passed == len(results) else 1)
