"""地图精确定位（GPT Round 28 第 5 轮的验收要求）。

问题：Map 组件用「筛选后的 events」找 selected，从工作台跳进来时该活动可能被筛掉，
导致 find 返回空 → 不居中，停在写死的默认中心。

修法：
1. 优先在 dataset.events（全量）里找 selected，被筛掉也能定位；
2. 用 ref 记住上次聚焦的活动 id，只在「聚焦目标变化」时居中，
   用户手动拖动地图后不会被无关重渲染拉回；
3. 无有效坐标时不移动、不清空详情（页面上由调用方显示「暂无准确位置」）。
"""
from pathlib import Path

root = Path(__file__).resolve().parent.parent
target = root / "frontend" / "src" / "components" / "Map" / "index.tsx"
text = target.read_text(encoding="utf-8")

if "lastFocusedId" not in text:
    text = text.replace(
        "  const container = useRef<HTMLDivElement>(null);",
        "  // 只在聚焦目标变化时居中，避免用户手动拖动后被反复拉回\n"
        "  const lastFocusedId = useRef<string | null>(null);\n"
        "  const container = useRef<HTMLDivElement>(null);",
        1,
    )

old_center = """    const event = events.find((e) => e.id === selected);
    const c = event ? eventCoordinates(event, dataset) : null;
    if (c) map.current.setZoomAndCenter(14, [c.lng, c.lat]);"""
new_center = """    // 关键：在全量数据集里找，避免该活动被当前筛选条件筛掉后无法定位
    const focusEvent =
      dataset.events.find((e) => e.id === selected) ?? events.find((e) => e.id === selected);
    const focus = focusEvent ? eventCoordinates(focusEvent, dataset) : null;
    if (focus && lastFocusedId.current !== selected) {
      lastFocusedId.current = selected;
      map.current.setZoomAndCenter(15, [focus.lng, focus.lat]);
    }"""
if old_center in text:
    text = text.replace(old_center, new_center, 1)

target.write_text(text, encoding="utf-8")
print("  已改居中逻辑:", "lastFocusedId" in target.read_text(encoding="utf-8"))
print("  依赖数组含 dataset:", "dataset," in target.read_text(encoding="utf-8"))
