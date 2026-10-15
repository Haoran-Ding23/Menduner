"""修正残缺的场馆名并把坐标补上。

## 为什么是显式映射而不是规则

这 6 个名字残缺的原因各不相同，而且残缺名**不是**完整名的前缀：

    苏州文化中心大道喜剧院   vs  苏州文化艺术中心     「艺术」在中间，不是前缀
    苏州文化艺中心魔术剧场    vs  苏州文化艺术中心     来源标题本身就漏了一个字
    展厅                  vs  嘉德·宥爱艺术中心     真实场馆只出现在地址字段
    大闸蟹文化馆            vs  阳澄湖大闸蟹文化馆    缺了前缀

我试过写一条通用规则（「名字以 中心/剧场/剧院/大厅 结尾时，取以其为前缀的已知长名」），
它对**全部 5 个都返回 None** —— 前提就是错的。用一个凑不出来的规则去套 5 个特例，
不如写一张可复核的表。所以做法与 `venue_aliases.json` 一致：显式、逐条、带依据。

## 保留原名

**不改写 `name`**：它是来源页面原文，属于证据。新增 `canonicalName` 记录
「我们用来查询的完整名」，两者并存，任何人都能看出改了什么、为什么。

坐标一律取自高德返回的真实坐标与 place id，不手写任何坐标值。
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import venues as venue_store
from backend.database import connect

DB = Path(os.environ.get(
    "MENDUNER_DB_PATH",
    "/srv/menduner/data/menduner.sqlite3" if Path("/srv/menduner/data/menduner.sqlite3").exists()
    else ROOT / "backend" / "data" / "menduner.sqlite3",
))
REVIEWER = "menduner-lead"

# venue_id: (完整名, 依据, 高德坐标, 高德 place id, 高德返回的地址, 状态)
FIXES = {
    "venue-5e8e49885436e2278dba": (
        "苏州文化艺术中心",
        "来源标题写作「苏州文化艺中心」（漏「术」）；该场馆活动名为"
        "「苏州文化艺术中心:互动魔术秀《开放麦吉克》」，地址记录 观枫街1号，两者一致",
        (120.702502, 31.321244), "B0FFG9VC8P", "观枫街1号(近现代大道)", "Verified"),
    "venue-cee55ce4b2b33886a90d": (
        "苏州文化艺术中心",
        "名称是「区域+大厅」组合；活动名「苏州文化艺术中心:『百年琴脉』吴门琴派艺术特展」，"
        "地址记录 观枫街1号，与苏州文化艺术中心一致",
        (120.702502, 31.321244), "B0FFG9VC8P", "观枫街1号(近现代大道)", "Verified"),
    "venue-e74732c331cb93e8c18b": (
        "苏州大道喜剧院",
        "来源标题写作「苏州文化中心」，地址记录 观枫街1号；高德有独立的「苏州大道喜剧院」",
        (120.702613, 31.321611), "B0FFHXVBQ7", "苏州工业园区环金鸡湖步道金鸡湖美术馆", "Verified"),
    "venue-3b3d2398044c53bc7d12": (
        "嘉德·宥爱艺术中心",
        "名称是通用词「展厅」；**真实场馆只出现在地址字段**「假日街7号嘉德·宥爱艺术中心2号」，"
        "高德候选地址为 假日街7号，完全一致",
        (120.755824, 31.400898), "B0FFHZWZ6G", "假日街7号", "Verified"),
    "venue-e5e922ef44d370d7b1c1": (
        "阳澄湖大闸蟹文化馆",
        "名称缺前缀；补全为「阳澄湖大闸蟹文化馆」后高德命中，地址 阳澄湖镇消泾村消泾河南2号",
        (120.797011, 31.510896), "B0FFJ2XK3L", "阳澄湖镇消泾村消泾河南2号", "Verified"),
    "venue-eeea18b704cfbb7ce8de": (
        "苏州市桂花公园",
        "名称缺市名前缀；地址记录 竹辉路1号 与高德候选地址完全一致",
        (120.642676, 31.291563), "B020016FEO", "竹辉路1号(竹辉桥地铁站1西南口步行470米)", "Verified"),
    # 名称可修正，但坐标性质是「景区范围」而非单一建筑，标注为待复核而非已核验。
    "venue-aaa319d1007688b0928f": (
        "莲花岛景区",
        "名称是「阳澄湖莲花岛」，高德登记为「莲花岛景区」；面积型景区没有单一入口点，"
        "坐标取景区 POI 而非北/南码头，状态留 Needs Review",
        (120.817148, 31.483324), "B0FFHZQ3T4", "阳澄湖镇莲花村西洋村相石路30号莲花岛内(北侧)",
        "Needs Review"),
}

ap = argparse.ArgumentParser()
ap.add_argument("--db", type=Path, default=DB)
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

con = sqlite3_connect = None
with connect(args.db) as con:
    rows = {r["id"]: json.loads(r["payload"]) for r in
            con.execute("SELECT id, payload FROM venues")}

print(f"库: {args.db}")
print(f"场馆: {len(rows)}")
print()
print(f"=== 将修正 {len(FIXES)} 个 ===")
plan = []
for vid, (full, why, (lng, lat), poi_id, addr, status) in FIXES.items():
    cur = rows.get(vid)
    if not cur:
        print(f"  ! {vid} 不存在")
        continue
    plan.append({"id": vid, "current": cur.get("name"), "full": full, "why": why,
                 "lng": lng, "lat": lat, "poi_id": poi_id, "addr": addr, "status": status})
    print()
    print(f"  {str(cur.get('name'))[:34]}")
    print(f"    -> 查询用名: {full}")
    print(f"    依据: {why}")
    print(f"    坐标: {lng},{lat}  高德地址: {addr}  状态: {status}")

if not args.apply:
    print()
    print(f"  DRY RUN：未写入。加 --apply 执行（{len(plan)} 个）")
    sys.exit(0)

print()
print("=== 写入 ===")
now = datetime.now(timezone.utc).isoformat()
for item in plan:
    # 1) 记录查询用名（不改写 name —— name 是来源原文）
    with connect(args.db) as con:
        row = con.execute("SELECT payload FROM venues WHERE id=?", (item["id"],)).fetchone()
        payload = json.loads(row["payload"])
        payload["canonicalName"] = item["full"]
        payload["canonicalNameReason"] = item["why"]
        con.execute("UPDATE venues SET payload=? WHERE id=?",
                    (json.dumps(payload, ensure_ascii=False, sort_keys=True), item["id"]))
    # 2) 写坐标与出处
    venue_store.set_coordinates(
        args.db,
        venue_id=item["id"],
        lng=item["lng"],
        lat=item["lat"],
        source_url=f"https://ditu.amap.com/place/{item['poi_id']}",
        reviewer=REVIEWER,
        note=f"名称修正为「{item['full']}」后查得。依据：{item['why']}",
        system="GCJ-02",
        status=item['status'],
    )
    print(f"  ✓ {str(item['current'])[:28]:30s} -> {item['full'][:26]:28s} {item['lng']:.6f},{item['lat']:.6f}")

print()
print("=== 复核 ===")
with connect(args.db) as con:
    total = 0
    withcoord = 0
    needs = 0
    for r in con.execute("SELECT payload FROM venues"):
        p = json.loads(r[0])
        total += 1
        if p.get("coordinates"):
            withcoord += 1
            if (p["coordinates"] or {}).get("status") != "Verified":
                needs += 1
    ev = [(r["venue"],) for r in con.execute("SELECT venue FROM events")]
    print(f"  场馆 {total}，有坐标 {withcoord}")
    print(f"  坐标状态非 Verified: {needs}")
    print(f"  integrity: {con.execute('PRAGMA integrity_check').fetchone()[0]}")
    print(f"  foreign_key: {len(con.execute('PRAGMA foreign_key_check').fetchall())} 个问题")
