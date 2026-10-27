"""把商圈地图接到「商圈洞察」页：总览 KPI 之后、Top10 之前（GPT Round 20 的位置要求）。"""
from pathlib import Path

page = Path(__file__).resolve().parent.parent / "frontend" / "src" / "pages" / "DistrictInsights" / "index.tsx"
s = page.read_text(encoding="utf-8")

if "MarketAreaMap" not in s:
    s = s.replace('import Chart from "../../components/Charts";',
                  'import Chart from "../../components/Charts";\n'
                  'import MarketAreaMap from "../../components/MarketAreaMap";', 1)

    anchor = '      {/* ② 主图 + 辅助图 */}'
    block = '''      {/* 商圈地图：选中中心画 800 米范围圆，其余只画点（不画假边界） */}
      {areas.length > 0 && (
        <section className="insight-card" aria-label="商圈地图">
          <div className="card-head">
            <h3>商圈地图</h3>
            <span className="insight-muted">
              蓝＝官方商圈 · 青＝参考地点 · 选中后显示该地点 {radius} 米范围（不是正式边界）
            </span>
          </div>
          <MarketAreaMap
            height={420}
            selectedId={selected}
            onSelect={setSelected}
            areas={areas
              .filter((area) => area.centerSource !== null || true)
              .map((area) => ({
                id: area.id,
                name: area.name,
                status: area.status,
                lng: 0,
                lat: 0,
                radiusMeters: area.radiusMeters,
              }))}
          />
        </section>
      )}

''' + anchor
    s = s.replace(anchor, block, 1)
    page.write_text(s, encoding="utf-8")

print("  已挂载地图:", "MarketAreaMap" in page.read_text(encoding="utf-8"))
print("  注意：坐标需由接口补", "lng: 0" in page.read_text(encoding="utf-8"))
