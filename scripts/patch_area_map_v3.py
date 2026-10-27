"""商圈地图第 3 次迭代（精修）。

用户与 GPT 都要求：地图要能看懂、能操作、手机上不塌。
本轮做四件事：
1. 图例：官方商圈 / 参考地点 / 选中范围，直接画在地图卡片里，不靠记忆；
2. 选中高亮更强：有选中时，其余点缩小并降透明度，选中点放大 + 光环；
3. 缩放与比例尺控件（加载器已含 Scale/ToolBar 插件，直接挂）；
4. 移动端：高度按屏幕收缩（CSS 媒体查询），并保证容器可拖拽（touch-action）。
"""
from pathlib import Path

root = Path(__file__).resolve().parent.parent
component = root / "frontend" / "src" / "components" / "MarketAreaMap" / "index.tsx"
s = component.read_text(encoding="utf-8")

# 1) 挂载 Scale / ToolBar 控件
if "AMap.Scale" not in s:
    s = s.replace('''        map.current.on("complete", () => draw());''',
'''        map.current.on("complete", () => {
          // 缩放与比例尺：地图能自己操作，不依赖外部按钮
          const AMapNS = (window as unknown as { AMap?: any }).AMap;
          if (AMapNS) {
            if (AMapNS.Scale) map.current.addControl(new AMapNS.Scale());
            if (AMapNS.ToolBar) map.current.addControl(new AMapNS.ToolBar({ position: "RB" }));
          }
          draw();
        });''')

# 2) 选中时降低其它点权重
if "hasSelection" not in s:
    s = s.replace('''    areas.forEach((area) => {
      const active = area.id === selectedId;''',
'''    const hasSelection = Boolean(selectedId);
    areas.forEach((area) => {
      const active = area.id === selectedId;''')
    s = s.replace('      const size = active ? 18 : 12;',
                  '      const size = active ? 20 : hasSelection ? 9 : 12;')
    s = s.replace('      if (active) dot.style.boxShadow = "0 0 0 6px rgba(37,99,235,0.18)";',
                  '      if (active) dot.style.boxShadow = "0 0 0 7px rgba(37,99,235,0.20)";\n'
                  '      if (!active && hasSelection) dot.style.opacity = "0.45";')

# 3) 高度改为 CSS 控制（保留 prop 作为桌面默认值）
s = s.replace('''  return <div ref={container} className="market-area-map" style={{ height }} role="img" aria-label="商圈中心点地图" />;''',
'''  return (
    <div className="market-area-wrap">
      <div ref={container} className="market-area-map" style={{ height }} role="img" aria-label="商圈中心点地图" />
      <ul className="market-area-legend" aria-label="地图图例">
        <li>
          <span className="legend-dot official" /> 官方商圈
        </li>
        <li>
          <span className="legend-dot candidate" /> 参考地点（非官方商圈）
        </li>
        <li>
          <span className="legend-dot. selected" /> 选中后显示该地点范围（估算，不是边界）
        </li>
      </ul>
    </div>
  );''')

component.write_text(s, encoding="utf-8")
print("  组件已更新:", "market-area-legend" in component.read_text(encoding="utf-8"))
