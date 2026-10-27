"""修正页头引导句被 CSS 隐藏的问题。

global.css 里有 `.page-heading > p { display: none; }`（为了保持页头紧凑），
插在 .page-heading 内部的 <p> 会被隐藏（实测 display: none）。
所以把引导句移到 .page-heading 之外，作为页面正文的第一段。
"""
from pathlib import Path

root = Path(__file__).resolve().parent.parent

specs = [
    ("frontend/src/pages/CityEventMap/index.tsx",
     "先找到酒店周边值得关注的活动，再查看它与场馆、商圈的关系。",
     "<Filters regions={false} />"),
    ("frontend/src/pages/KnowledgeGraph/index.tsx",
     "先看活动在哪里举办、与哪些地区相关；有疑问，再核对关系和来源。",
     "      <GraphRelationSummary"),
    ("frontend/src/pages/DataQuality/index.tsx",
     "先核对影响活动判断的关键信息，确认后更新关联关系的可信状态。",
     '      <Alert'),
]

for relative, sentence, anchor in specs:
    path = root / relative
    text = path.read_text(encoding="utf-8")
    # 1) 删掉 page-heading 里的那一行
    for candidate in [
        f'        <p className="page-lead">{sentence}</p>\n',
        f'          <p className="page-lead">{sentence}</p>\n',
        f'      <p className="page-lead">{sentence}</p>\n',
        f'        <p className="page-lead">{sentence}</p>\r\n',
    ]:
        if candidate in text:
            text = text.replace(candidate, "", 1)
            break
    # 2) 在锚点之前插入
    if anchor in text:
        indent = " " * (len(text[: text.find(anchor)].split("\n")[-1]))
        block = f'{indent}<p className="page-lead">{sentence}</p>\n'
        text = text.replace(anchor, block + anchor, 1)
        path.write_text(text, encoding="utf-8")
        print("  已移到正文:", relative)
    else:
        path.write_text(text, encoding="utf-8")
        print("  ⚠ 锚点未找到:", relative)
