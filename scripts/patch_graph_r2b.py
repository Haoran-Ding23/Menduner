"""12 轮第 2 轮（图谱页）：画布与图层工具栏按需渲染。"""
from pathlib import Path

page = Path(__file__).resolve().parent.parent / "frontend" / "src" / "pages" / "KnowledgeGraph" / "index.tsx"
s = page.read_text(encoding="utf-8")

# 1) 页面级状态：默认不渲染画布
if "showCanvas" not in s:
    s = s.replace("  const [nodeId, setNodeId] = useState<string | null>(null),",
                  "  // 渐进式披露：默认只显示关系摘要，画布按需渲染（初始 DOM 里没有 ReactFlow）\n"
                  "  const [showCanvas, setShowCanvas] = useState(false);\n"
                  "  const [nodeId, setNodeId] = useState<string | null>(null),", 1)

# 2) 摘要按钮 → 打开画布
s = s.replace("<GraphRelationSummary eventId={id} />",
              "<GraphRelationSummary eventId={id} onOpenGraph={() => setShowCanvas(true)} />")

# 3) 工具栏 + 画布布局包进条件渲染
start = s.find('      <div className="panel graph-toolbar">')
if start > 0 and "{showCanvas && (" not in s:
    # 找到 graph-layout 的结束：页面里 </div> 之后紧跟 node-panel 或结束
    layout_end = s.find('      <section className="panel node-panel">', start)
    if layout_end < 0:
        layout_end = s.find("    </>", start)
    block = s[start:layout_end]
    indented = "\n".join(("  " + line) if line.strip() else line for line in block.splitlines())
    replacement = ('      {showCanvas ? (\n'
                   '        <>\n'
                   f'{indented}\n'
                   '          <div style={{ marginTop: 8 }}>\n'
                   '            <Button size="small" onClick={() => setShowCanvas(false)}>\n'
                   '              收起关系图\n'
                   '            </Button>\n'
                   '          </div>\n'
                   '        </>\n'
                   '      ) : (\n'
                   '        <section className="panel gap-bottom" aria-label="关系图未展开">\n'
                   '          <p className="muted" style={{ margin: 0 }}>\n'
                   '            关系图默认收起：上面已经用一句句话说明了这场活动在哪办、离哪些酒店多近、\n'
                   '            信息靠不靠谱。需要看节点与连线时，点摘要里的「查看关系图」。\n'
                   '          </p>\n'
                   '        </section>\n'
                   '      )}\n\n')
    s = s[:start] + replacement + s[layout_end:]

page.write_text(s, encoding="utf-8")
print("  画布默认不渲染:", "showCanvas" in page.read_text(encoding="utf-8"))
