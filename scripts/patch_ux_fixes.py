"""修三处：商圈地图点选不再放大、商圈洞察默认展开活动列表、地图页不再自动弹详情。

用户反馈原话：
1「点击这个商圈，地图会变大，能不能维持在之前我看地图的时候」
2「在商圈洞察多一个，可以看到商圈内的活动」
3「为什么一点开这个城市活动地图就挑出这个页面（活动详情抽屉）」
"""
from pathlib import Path

root = Path(__file__).resolve().parent.parent

# ---- 1) 商圈地图：点选只画圆，不改变缩放/中心 ----
map_file = root / "frontend" / "src" / "components" / "MarketAreaMap" / "index.tsx"
m = map_file.read_text(encoding="utf-8")
m = m.replace('      map.current.setZoomAndCenter(13, [active.lng, active.lat]);',
              '      // 不改变用户当前的缩放与中心：只画范围圆，避免"点一下就变大变位"（用户反馈过）')
map_file.write_text(m, encoding="utf-8")
print("  商圈地图不再自动缩放:", "不改变用户当前的缩放" in map_file.read_text(encoding="utf-8"))

# ---- 2) 商圈洞察：活动列表默认展开 ----
insight = root / "frontend" / "src" / "pages" / "DistrictInsights" / "index.tsx"
s = insight.read_text(encoding="utf-8")
if "defaultActiveKey" not in s:
    s = s.replace('          items={[{\n            key: "activities",',
                  '          defaultActiveKey={["activities"]}\n          items={[{\n            key: "activities",', 1)
    insight.write_text(s, encoding="utf-8")
print("  活动列表默认展开:", "defaultActiveKey" in insight.read_text(encoding="utf-8"))

# ---- 3) 地图页：只有 URL 明确带 detail 才自动开详情 ----
page = root / "frontend" / "src" / "pages" / "CityEventMap" / "index.tsx"
p = page.read_text(encoding="utf-8")
if "allowAutoDetail" not in p:
    p = p.replace("  useEffect(() => {\n    const params = new URLSearchParams(window.location.search);",
'''  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    // 只有在链接里明确写了 detail 时才自动打开详情抽屉；
    // 从导航进地图不应该被上一次的详情状态弹窗打断（用户反馈过）
    if (!params.get("detail")) {
      update({ detail: null });
    }''', 1)
    page.write_text(p, encoding="utf-8")
print("  不再自动弹详情:", "链接里明确写了 detail" in page.read_text(encoding="utf-8"))
