"""12 轮第 12 轮收尾：按 GPT Round 33 的建议，给三个页面各加一句业务路径引导。

地图：「先找到酒店周边值得关注的活动，再查看它与场馆、商圈的关系。」
图谱：「先看活动在哪里举办、与哪些地区相关；有疑问，再核对关系和来源。」
审核台：「先核对影响活动判断的关键信息，确认后更新关联关系的可信状态。」
"""
from pathlib import Path

root = Path(__file__).resolve().parent.parent

targets = [
    ("frontend/src/pages/CityEventMap/index.tsx",
     "先找到酒店周边值得关注的活动，再查看它与场馆、商圈的关系。"),
    ("frontend/src/pages/KnowledgeGraph/index.tsx",
     "先看活动在哪里举办、与哪些地区相关；有疑问，再核对关系和来源。"),
    ("frontend/src/pages/DataQuality/index.tsx",
     "先核对影响活动判断的关键信息，确认后更新关联关系的可信状态。"),
]

for relative, sentence in targets:
    path = root / relative
    text = path.read_text(encoding="utf-8")
    if sentence in text:
        print("  已有引导:", relative)
        continue
    # 找页面主标题 h1 所在行，在其后插入引导句
    marker = "<h1"
    index = text.find(marker)
    if index < 0:
        print("  ⚠ 未找到 h1:", relative)
        continue
    close = text.find("</h1>", index)
    if close < 0:
        print("  ⚠ h1 未闭合:", relative)
        continue
    insert_at = close + len("</h1>")
    line_start = text.rfind("\n", 0, index) + 1
    indent = " " * (index - line_start)
    block = f'\n{indent}<p className="page-lead">{sentence}</p>'
    path.write_text(text[:insert_at] + block + text[insert_at:], encoding="utf-8")
    print("  已加引导:", relative)

css = """

/* 页头业务路径引导 */
.page-lead {
  margin: 6px 0 16px;
  font-size: 13.5px;
  line-height: 20px;
  color: #64748b;
}
"""
style = root / "frontend" / "src" / "styles" / "global.css"
style.write_text(style.read_text(encoding="utf-8") + css, encoding="utf-8")
print("  样式已加")
