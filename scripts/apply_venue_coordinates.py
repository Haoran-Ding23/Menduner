"""为缺坐标的场馆补坐标——逐条人工判定，不靠名字相似度自动写。

## 判据

主判据是**地址**，不是名字相似度：

* 场馆记录里已有地址的（如 `苏州湾博物馆` = 东太湖大道12000号），
  高德返回的候选地址必须对得上；
* 没有地址的，名字必须完整（不是子设施），且类型对（不是停车场/售票处/码头/店铺）。

## 为什么不用「部分匹配就写」

`scripts/enrich_venue_coordinates.py` 的保守策略是对的，它只是把 35 个全打进了人工队列。
它们里面确实混着错的：

    李公堤文化创意街区  → 「李公堤文化创意街区停车场」   四季路5号（不是本体的地址）
    白马涧龙池景区     → 「...聆泉桥」                桥不是景区
    苏州竹辉环宇荟     → 「M Stand(...店)」           一家咖啡店
    苏州市体育中心体育馆 → 「...地下停车场(出入口)」      停车场

批量放行会把这些写成「已核验」，比缺坐标更糟。

每条判定都写明依据，方便复核。使用高德返回的真实坐标与 place id，
不手写任何坐标值。
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx

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

# 场馆名 -> (高德 POI 名, 依据)
#
# 依据里的地址来自场馆记录（venue_address）或高德返回，两者一致才写。
ACCEPT = {
    "中国苏州评弹博物馆“吴苑深处”书场": (
        "中国苏州评弹博物馆", "场馆地址 中张家巷3号 与候选地址一致；书场在馆内"),
    "乐动力昆山奥体中心": ("昆山奥体中心", "同属昆山奥体中心；地址 东城北大道333号"),
    "光裕书厅": ("光裕书厅(观前街店)", "唯一候选；名称含场馆名加门店后缀"),
    "大阳山景区": ("江苏大阳山国家森林公园大阳山景区", "名称完整包含场馆名；地址 山神湾路"),
    "太仓市博物馆": ("太仓博物馆", "太仓市唯一博物馆；地址 上海东路100号"),
    "定慧寺巷口凤凰街旅游咨询中心": (
        "苏州市旅游咨询中心(凤凰街中心站)", "候选地址 凤凰街276号 与场馆地址完全一致"),
    "山丘livehouse-斜塘店": ("山丘咖啡", "候选地址 松涛街1088号斜塘老街36幢 与场馆地址一致"),
    "山丘livehouse-红唐店": ("山丘Livehouse(红唐店)", "名称匹配红唐店；地址 滨河路999号"),
    "常熟市文化艺术中心展厅": (
        "常熟市文化艺术中心", "候选地址 星光路8号 与场馆地址 琴川街道星光路8号 一致；展厅在中心内"),
    "常熟市图书馆": ("常熟图书馆", "候选地址 书院街27号 与场馆地址 书院街27号 一致"),
    "苏州之眼": ("苏州之眼摩天轮", "唯一同名候选；地址 右岸街99号 与场馆地址一致"),
    "苏州博物馆": ("苏州博物馆(本馆)", "候选地址 东北街204号 与场馆地址完全一致"),
    "苏州图书馆": ("苏州图书馆(人民路总馆)", "候选地址 人民路858号 与场馆地址完全一致"),
    "苏州寒山寺和合美术馆": ("和合美术馆", "名称核心一致；地址在寒山寺内，与场馆地址 寒山寺弄24号 相符"),
    "苏州工业园区城市艺术客厅": (
        "苏州工业园区城市艺术客厅(圆融时代广场店)",
        "候选地址 旺墩路268号圆融时代广场 与场馆地址一致"),
    "苏州文化中心国风剧场": (
        "苏州文化艺术中心-1号国风剧场", "候选地址 观枫街1号 与场馆地址一致；国风剧场在艺术中心内"),
    "苏州文化中心大剧院": (
        "苏州文化艺术中心大剧院", "候选地址 观枫街1号 与场馆地址一致"),
    "苏州湾博物馆": ("苏州市吴江区苏州湾博物馆", "候选地址 东太湖大道12000号 与场馆地址完全一致"),
    "苏州第一丝厂": (
        "苏州第一丝厂文化产业园区", "园区即场馆本体；高德地址 南门路83号，场馆记 南门路94号，同址段"),
    "苏州竹辉环宇荟": ("环宇荟购物中心", "候选地址 竹辉路168号 与场馆地址完全一致"),
    "苏州市体育中心体育馆": (
        "苏州市体育中心(建设中)", "候选地址 三香路1131号 与场馆地址完全一致"),
    "虎丘山风景名胜区": ("虎丘山风景区", "名称核心一致；地址 虎丘山门内8号"),
    "李公堤文化创意街区": ("李公堤国际风情商业水街", "李公堤本体商业街；停车场候选不采用"),
    "白马涧龙池景区": ("白马涧龙池风景区", "名称核心一致；地址在白马涧生态园（桥候选不采用）"),
    "狮山大剧院": ("苏州狮山大剧院", "名称加市名前缀；地址 长江路与狮山路交叉口"),
    "琵琶语评弹茶馆-平江路北馆": (
        "琵琶语评弹馆(平江路北馆)", "名称核心一致，同为平江路北馆"),
    "长歌演艺空间": (
        "长歌剧场·脱口秀·日咖夜酒(观前街店)", "名称核心一致；候选地址 皮市街9-69号 与场馆地址一致"),
}

# 明确不写，并记录原因（不静默跳过）
REJECT = {
    "展厅": "场馆名是通用词，真实场馆只出现在地址字段里；需要先修名称",
    "大闸蟹文化馆": "只找到同名农家乐，不是文化馆",
    "阳澄湖莲花岛": "候选是岛内码头/景区局部，场馆本身是整岛",
    "苏州文化艺中心魔术剧场": "场馆名本身有错字（应为「苏州文化艺术中心」），先修名称再查",
    "苏艺演艺文化集聚区公共区域|大珍珠大厅": "名称是区域+大厅组合，需人工指定具体点",
    "桂花公园": "地址一致但缺场馆名同证，留待复核（避免只凭地址写入）",
    # 这条最重要：地址直接否定了候选。
    "张家港市美术馆": "候选「苏华美术馆」地址为长安中路，场馆记录为东苑路308号，地址不一致，不写",
    # 场馆名与地址都指向文化艺术中心片区，但候选地址与记录地址不同源。
    "苏州文化中心大道喜剧院": "候选「苏州大道喜剧院」地址在金鸡湖美术馆，场馆记录为观枫街1号，地点存疑，不写",
}

ap = argparse.ArgumentParser()
ap.add_argument("--db", type=Path, default=DB)
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

CAND = ROOT / "amap_candidates.json"
if not CAND.exists():
    CAND = Path("/srv/menduner/amap_candidates.json")
data = json.loads(CAND.read_text(encoding="utf-8"))
by_name = {row["venue_name"]: row for row in data}

print(f"库: {args.db}")
print(f"候选文件: {CAND}  ({len(data)} 个场馆)")
print()
print(f"=== 判定为「写入」: {len(ACCEPT)} 个 ===")
plan = []
for venue_name, (poi_name, why) in ACCEPT.items():
    row = by_name.get(venue_name)
    if not row:
        print(f"  ! {venue_name}: 候选文件里没有")
        continue
    hit = next((c for c in row["candidates"] if c["name"] == poi_name), None)
    if not hit:
        print(f"  ! {venue_name}: 找不到候选 POI「{poi_name}」")
        continue
    lng, lat = (float(x) for x in hit["location"].split(","))
    plan.append({
        "venue_id": row["venue_id"], "venue_name": venue_name,
        "poi_name": poi_name, "address": hit["address"], "poi_id": hit["id"],
        "lng": lng, "lat": lat, "why": why, "events": row["events"],
    })
    print(f"  {venue_name[:26]:28s} -> {poi_name[:28]:30s} {lng:.6f},{lat:.6f}")
    print(f"      {why}")

print()
print(f"=== 判定为「不写」: {len(REJECT)} 个 ===")
for name, why in REJECT.items():
    print(f"  {name[:34]:36s} {why}")

missing = [n for n in by_name if n not in ACCEPT and n not in REJECT]
if missing:
    print()
    print(f"=== 未判定（{len(missing)} 个）===")
    for n in missing:
        print(f"  {n}")

if not args.apply:
    print()
    print(f"  DRY RUN：未写入。加 --apply 执行（{len(plan)} 个）")
    sys.exit(0)

print()
print("=== 写入 ===")
ok = fail = 0
for item in plan:
    try:
        venue_store.set_coordinates(
            args.db,
            venue_id=item["venue_id"],
            lng=item["lng"],
            lat=item["lat"],
            source_url=f"https://ditu.amap.com/place/{item['poi_id']}",
            reviewer=REVIEWER,
            note=f"人工判定：{item['why']}（高德 POI「{item['poi_name']}」，地址 {item['address']}）",
        )
        ok += 1
        print(f"  ✓ {item['venue_name'][:30]:32s} {item['lng']:.6f},{item['lat']:.6f}")
    except Exception as exc:
        fail += 1
        print(f"  ✗ {item['venue_name'][:30]:32s} {type(exc).__name__}: {exc}")
    time.sleep(0.05)

print()
print(f"  写入 {ok}，失败 {fail}")
with connect(args.db) as con:
    total = con.execute("SELECT COUNT(*) FROM venues").fetchone()[0]
    withcoord = 0
    for r in con.execute("SELECT payload FROM venues"):
        p = json.loads(r[0])
        if p.get("coordinates"):
            withcoord += 1
print(f"  场馆 {total}，其中有坐标 {withcoord}")
