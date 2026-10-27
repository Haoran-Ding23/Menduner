"""商圈列表接口补中心点坐标，并把地图接到页面（用真实坐标，不写 0）。"""
from pathlib import Path

root = Path(__file__).resolve().parent.parent

# 1) 后端：ranking 返回中心点坐标
backend = root / "backend" / "market_area.py"
b = backend.read_text(encoding="utf-8")
if '"centerLng"' not in b:
    b = b.replace('''            "parentName": result["parents"].get(area["parentId"]),''',
'''            "parentName": result["parents"].get(area["parentId"]),
            "centerLng": area["center"]["lng"],
            "centerLat": area["center"]["lat"],
            "centerSource": area["center"].get("source"),''')
    backend.write_text(b, encoding="utf-8")
print("  后端已返回坐标:", '"centerLng"' in backend.read_text(encoding="utf-8"))

# 2) 前端类型
api = root / "frontend" / "src" / "services" / "api.ts"
t = api.read_text(encoding="utf-8")
if "centerLng" not in t:
    t = t.replace('''  centerSource: string | null;''',
'''  centerLng: number;
  centerLat: number;
  centerSource: string | null;''')
    api.write_text(t, encoding="utf-8")
print("  类型已补:", "centerLng" in api.read_text(encoding="utf-8"))

# 3) 页面挂载（真实坐标）
page = root / "frontend" / "src" / "pages" / "DistrictInsights" / "index.tsx"
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
            areas={areas.map((area) => ({
              id: area.id,
              name: area.name,
              status: area.status,
              lng: area.centerLng,
              lat: area.centerLat,
              radiusMeters: area.radiusMeters,
            }))}
          />
        </section>
      )}

''' + anchor
    s = s.replace(anchor, block, 1)
    page.write_text(s, encoding="utf-8")
print("  已挂载地图:", "MarketAreaMap" in page.read_text(encoding="utf-8"))
