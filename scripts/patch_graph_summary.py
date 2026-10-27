"""把「活动关系摘要」挂到 /graph 页面顶部，并把原图谱改为可折叠的「关系图」。

GPT Round 29（以酒店经理为准）：默认给人话摘要，图谱退到「查看关系图」后面。
这里先在页面顶部插入摘要组件；原图谱内容保留不动（不删功能）。
"""
from pathlib import Path

page = Path(__file__).resolve().parent.parent / "frontend" / "src" / "pages" / "KnowledgeGraph" / "index.tsx"
s = page.read_text(encoding="utf-8")

if "GraphRelationSummary" not in s:
    s = s.replace(
        'import GraphQueries from "../../components/GraphQueries";',
        'import GraphQueries from "../../components/GraphQueries";\n'
        'import GraphRelationSummary from "../../components/GraphRelationSummary";',
        1,
    )
    # 插在页头之后（page-heading 的结束 </div> 之后）
    anchor = '      <section className="panel gap-bottom" aria-label="图谱业务查询">'
    block = '      <GraphRelationSummary eventId={id} />\n\n' + anchor
    if anchor in s:
        s = s.replace(anchor, block, 1)
    page.write_text(s, encoding="utf-8")

print("  已挂载关系摘要:", "GraphRelationSummary" in page.read_text(encoding="utf-8"))
