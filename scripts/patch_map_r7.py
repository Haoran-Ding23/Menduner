"""12 轮第 7 轮（地图）：三层叠加的取舍、统一图例、加载/失败态。

GPT Round 32 第 7 轮：统一三层叠加、点聚合、图例和加载状态；
验收 = 三层同时开启不重复标记；切换无残留。

实现：
1. 商圈数据加载中/失败都有明确状态（失败可重试），不是一片空白；
2. 当酒店层也打开时，商圈点自动缩小降透明，避免三层叠在一起糊成一片；
3. 图例随打开的图层变化：活动分类 + 酒店 + 商圈点 + 选中范围，只列当前真正打开的那些。
"""
from pathlib import Path

root = Path(__file__).resolve().parent.parent

# ---------- Map：酒店层打开时，商圈点降权 ----------
mp = root / "frontend" / "src" / "components" / "Map" / "index.tsx"
m = mp.read_text(encoding="utf-8")
if "dimAreas" not in m:
    m = m.replace("""        el.style.background = area.status === "official" ? "#2563EB" : "#fff";""",
"""        // 三层同开时商圈点降权（缩小 + 半透明），避免和酒店标记糊在一起
        if (demandLayer && !active) {
          el.style.width = "9px";
          el.style.height = "9px";
          el.style.opacity = "0.7";
        }
        el.style.background = area.status === "official" ? "#2563EB" : "#fff";""", 1)
    m = m.replace("    areasLayer,\n    selectedArea,", "    areasLayer,\n    selectedArea,\n    demandLayer,", 1)
    mp.write_text(m, encoding="utf-8")
print("  Map 叠加降权:", "三层同开时商圈点降权" in mp.read_text(encoding="utf-8"))

# ---------- 页面：加载/失败态 + 动态图例 ----------
pg = root / "frontend" / "src" / "pages" / "CityEventMap" / "index.tsx"
s = pg.read_text(encoding="utf-8")

if "areaLoadState" not in s:
    s = s.replace('  const [areaRows, setAreaRows] = useState<',
                  '  const [areaLoadState, setAreaLoadState] = useState<"idle" | "loading" | "error">("idle");\n'
                  '  const [areaRows, setAreaRows] = useState<', 1)
    s = s.replace('''    if (!showAreas || areaRows.length) return;
    loadMarketAreas()
      .then((result) => setAreaRows(result))
      .catch(() => setAreaRows([]));''',
'''    if (!showAreas || areaRows.length) return;
    setAreaLoadState("loading");
    loadMarketAreas()
      .then((result) => {
        setAreaRows(result);
        setAreaLoadState("idle");
      })
      .catch(() => setAreaLoadState("error"));''')

    # 加载/失败提示（放在摘要条之前）
    s = s.replace('      {showAreas && selectedAreaId && (',
'''      {showAreas && areaLoadState === "loading" && (
        <div className="area-summary">
          <span className="muted">正在加载商圈参考点…</span>
        </div>
      )}
      {showAreas && areaLoadState === "error" && (
        <div className="area-summary">
          <span className="muted">商圈参考点加载失败（不影响活动与酒店）</span>
          <Button size="small" onClick={() => setAreaLoadState("idle")}>
            重试
          </Button>
        </div>
      )}
      {showAreas && selectedAreaId && (''', 1)

    # 动态图例：替换原 legend 内容
    s = s.replace('''          <div className="legend">
            {Object.values(categories).map((c) => (
              <span key={c.label}>
                <i style={{ background: c.color }} />
                {c.label}
              </span>
            ))}
          </div>''',
'''          <div className="legend">
            <span className="legend-item">
              <i style={{ background: "#dc2626" }} />
              活动点（按类别着色）
            </span>
            {showHotels && (
              <span className="legend-item">
                <i className="legend-hotel" />H 酒店
              </span>
            )}
            {showAreas && (
              <span className="legend-item">
                <i className="legend-area-official" />官方商圈
              </span>
            )}
            {showAreas && (
              <span className="legend-item">
                <i className="legend-area-candidate" />参考地点（非官方商圈）
              </span>
            )}
            {showAreas && selectedAreaId && (
              <span className="legend-item">
                <i className="legend-ring" />
                选中范围（估算，不是边界）
              </span>
            )}
          </div>''', 1)

    pg.write_text(s, encoding="utf-8")

print("  加载态:", "areaLoadState" in pg.read_text(encoding="utf-8"))
print("  动态图例:", "legend-area-official" in pg.read_text(encoding="utf-8"))
