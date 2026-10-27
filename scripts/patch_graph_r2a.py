"""12 轮第 2 轮（图谱）：默认只显示关系摘要，画布与周边设施按需展开。

GPT Round 32 第 2 轮要求：默认只显示活动关系摘要；关系图、周边设施、技术依据按需展开；
自动化验收 = 初始不渲染关系画布，点击后加载真实数据。

实现：
1. KnowledgeGraph：新增 showCanvas（默认 false），画布与工具栏只在展开时渲染；
   摘要组件里的「查看关系图」按钮改为调用页面级回调。
2. GraphRelationSummary：附近酒店/餐饮/交通默认收起，点「查看周边设施」才展开；
   移除组件内无效的 showGraph 状态。
"""
from pathlib import Path

root = Path(__file__).resolve().parent.parent

# ---- 1. 摘要组件：周边设施按需展开 + 画布回调 ----
summary = root / "frontend" / "src" / "components" / "GraphRelationSummary" / "index.tsx"
s = summary.read_text(encoding="utf-8")

s = s.replace(
    "export default function GraphRelationSummary({ eventId }: { eventId: string }) {",
    "export default function GraphRelationSummary({\n"
    "  eventId,\n"
    "  onOpenGraph,\n"
    "}: {\n"
    "  eventId: string;\n"
    "  onOpenGraph?: () => void;\n"
    "}) {",
)
s = s.replace("  const [showGraph, setShowGraph] = useState(false);",
              "  // 周边设施默认收起：摘要先回答“在哪办、靠不靠谱”，要看细节再点开\n"
              "  const [showNearby, setShowNearby] = useState(false);")

# 把「附近有什么」起、到 caveat 前的那段包进 showNearby 条件里
start = s.find('      {/* ② 离我的酒店多远 */}')
caveat = s.find('      <p className="relation-caveat">')
if start > 0 and caveat > start:
    body = s[start:caveat]
    body_indented = "\n".join(("  " + line) if line.strip() else line for line in body.splitlines())
    wrapped = ('      {/* ② 周边设施：默认收起，用户主动打开才出现 */}\n'
               '      {showNearby ? (\n'
               '        <>\n'
               f'{body_indented}\n'
               '        </>\n'
               '      ) : (\n'
               '        <Button size="small" onClick={() => setShowNearby(true)}>\n'
               '          查看周边设施（酒店 {chain.nearbyHotels.length} · 餐饮/交通/其他 {chain.nearbyPlaces.length}）\n'
               '        </Button>\n'
               '      )}\n\n')
    s = s[:start] + wrapped + s[caveat:]

s = s.replace('''        <Button size="small" onClick={() => setShowGraph((value) => !value)}>
          {showGraph ? "收起关系图" : "查看关系图"}
        </Button>''',
'''        <Button size="small" onClick={() => onOpenGraph?.()}>
          查看关系图
        </Button>''')

summary.write_text(s, encoding="utf-8")
print("  摘要：周边默认收起:", "showNearby" in summary.read_text(encoding="utf-8"))
print("  摘要：画布回调:", "onOpenGraph" in summary.read_text(encoding="utf-8"))
