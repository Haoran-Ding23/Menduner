"""Round 19 口径措辞修正：酒店 -> 已收录住宿设施，并补 Verified 语义说明。"""
from pathlib import Path

root = Path(__file__).resolve().parent.parent

page = root / "frontend" / "src" / "pages" / "DistrictInsights" / "index.tsx"
s = page.read_text(encoding="utf-8")
pairs = [
    ("<h3>周边已收录酒店</h3>", "<h3>周边已收录住宿设施</h3>"),
    ("周边已收录酒店明细（", "周边已收录住宿设施明细（"),
    ("<small>半径内已收录酒店</small>", "<small>半径内已收录住宿设施</small>"),
    ("周边已收录 {hotelCount} 家酒店", "周边已收录 {hotelCount} 家住宿设施"),
    (
        "平台已收录且有可信坐标的酒店，不等于该商圈全部酒店",
        "数据来自平台已收录的住宿 POI（高德），仅反映 800 米近邻范围内的样本分布，不代表全部在营酒店或完整竞争格局",
    ),
    (
        "候选点由 POI 聚类得到，未经政府或地图方确认为正式商圈。",
        "候选点由 POI 聚类得到，未经政府或地图方确认为正式商圈。住宿设施坐标来自高德 POI 且通过坐标系检查，"
        "但这不等于经人工实地核验其存在、位置与营业状态。",
    ),
]
for old, new in pairs:
    if old in s:
        s = s.replace(old, new)
page.write_text(s, encoding="utf-8")

backend = root / "backend" / "market_area.py"
t = backend.read_text(encoding="utf-8")
old_note = "仅统计平台已收录且有可信坐标的酒店，不等于该商圈全部酒店；也不构成竞争强弱排名。"
new_note = "仅统计平台已收录的住宿 POI（高德），已通过坐标系检查但未经人工实地核验；不代表全部在营酒店，也不构成竞争强弱排名。"
if old_note in t:
    t = t.replace(old_note, new_note)
backend.write_text(t, encoding="utf-8")

print("  页面已改名:", "周边已收录住宿设施" in page.read_text(encoding="utf-8"))
print("  后端 note 已改:", new_note[:12] in backend.read_text(encoding="utf-8"))
