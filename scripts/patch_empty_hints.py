"""便民化第 3 轮：空状态给下一步动作（商圈画像 / 工作台推荐 / 知识图谱摘要）。"""
from pathlib import Path

root = Path(__file__).resolve().parent.parent

css = '''

/* 空状态引导：一句人话 + 可点动作 */
.empty-hint {
  border: 1px dashed #cbd5e1; border-radius: 10px; padding: 14px 16px;
  background: #f8fafc; display: flex; flex-direction: column; gap: 6px;
}
.empty-hint strong { font-size: 13.5px; color: #0f172a; font-weight: 600; }
.empty-hint p { margin: 0; font-size: 12.5px; line-height: 18px; }
'''
style = root / "frontend" / "src" / "styles" / "global.css"
style.write_text(style.read_text(encoding="utf-8") + css, encoding="utf-8")

# ---- 商圈洞察：画像里没有可归属活动 / 没有住宿时给引导 ----
market = root / "frontend" / "src" / "pages" / "DistrictInsights" / "index.tsx"
m = market.read_text(encoding="utf-8")
if "EmptyHint" not in m:
    m = m.replace('import MarketAreaMap from "../../components/MarketAreaMap";',
                  'import EmptyHint from "../../components/EmptyHint";\n'
                  'import MarketAreaMap from "../../components/MarketAreaMap";', 1)

    m = m.replace('''                {profile.categories.length === 0 ? (
                  <p className="muted">窗口内没有可归属活动</p>
                ) : (''',
'''                {profile.categories.length === 0 ? (
                  <EmptyHint
                    title="这个月，这个地点还没有能对上的活动"
                    reason="可能是本月该范围活动较少，或活动场馆还没有可用的位置坐标。"
                    actions={[
                      { label: "看看 1200 米范围", onClick: () => setRadius(1200) },
                      { label: "看看 1500 米范围", onClick: () => setRadius(1500) },
                      { label: "换一个地点", onClick: () => setSelected(selected) },
                    ]}
                  />
                ) : (''')

    m = m.replace('''        {hotelCount === 0 ? (
          <p className="muted" style={{ padding: "8px 0" }}>暂无已收录酒店</p>
        ) : hotelCount < 3 ? (''',
'''        {hotelCount === 0 ? (
          <EmptyHint
            title="这个地点半径内还没有收录的住宿"
            reason="平台只统计已收录且有可用坐标的住宿，未收录不代表附近没有酒店。"
            actions={[
              { label: "扩大到 1200 米", onClick: () => setRadius(1200) },
              { label: "扩大到 1500 米", onClick: () => setRadius(1500) },
            ]}
          />
        ) : hotelCount < 3 ? (''')
    market.write_text(m, encoding="utf-8")
print("  商圈页空状态:", "EmptyHint" in market.read_text(encoding="utf-8"))

# ---- 工作台：七天推荐为空时给引导 ----
bench = root / "frontend" / "src" / "pages" / "Workbench" / "index.tsx"
b = bench.read_text(encoding="utf-8")
if "EmptyHint" not in b:
    b = b.replace('import { usePlatform } from "../../hooks/usePlatform";',
                  'import EmptyHint from "../../components/EmptyHint";\n'
                  'import { usePlatform } from "../../hooks/usePlatform";', 1)
    anchor = '        ) : (\n          <div className="workbench-list">'
    replacement = '''        ) : worthWatching.length === 0 ? (
          <EmptyHint
            title="这家酒店未来七天没有匹配到值得关注的活动"
            reason="可能本周活动较少，或活动场馆还没有可用坐标，距离算不出来。"
            actions={[
              { label: "看看本月全部活动", onClick: () => go("/map") },
              { label: "换一家酒店", onClick: () => go("/find-hotels") },
              { label: "查看数据质量", onClick: () => go("/evidence") },
            ]}
          />
        ) : (
          <div className="workbench-list">'''
    if anchor in b:
        b = b.replace(anchor, replacement, 1)
    bench.write_text(b, encoding="utf-8")
print("  工作台空状态:", "EmptyHint" in bench.read_text(encoding="utf-8"))
