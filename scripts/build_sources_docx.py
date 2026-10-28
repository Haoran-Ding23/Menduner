"""生成《数据来源（爬虫网站）清单》Word 文档。

数据来源：生产库 sources 表的真实记录 + 每个来源采集到的活动数（events.source 统计）。
不做任何编造：没有采集到活动的来源会明确写 0 并注明原因类别。
"""
import json
from datetime import datetime
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

ROOT = Path(r"C:\Users\haora\Desktop\Menduner")
RAW = json.loads((ROOT / "deliverables" / "sources-raw.json").read_text(encoding="utf-8"))

KIND_LABEL = {
    "government": "政府/官方机构",
    "venue": "场馆官方",
    "event_platform": "活动/票务平台",
    "media": "媒体",
    "tourism": "文旅",
    "community": "社区/同城",
    "social_media": "社交媒体",
}

FLOW = {
    "government": "公开发布页 → 列表/详情解析",
    "venue": "场馆官网演出/展会日程页",
    "event_platform": "公开活动列表与详情页",
    "media": "公开报道正文中的活动信息",
    "tourism": "政府文旅站点节庆日历",
    "community": "同城活动公开列表",
    "social_media": "MediaCrawler 公开笔记（仅标题/时间/地点/链接）",
}

doc = Document()

# 中文字体
style = doc.styles["Normal"]
style.font.name = "微软雅黑"
style.font.size = Pt(10.5)
style.element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")


def heading(text, level=1):
    p = doc.add_heading(text, level=level)
    for run in p.runs:
        run.font.name = "微软雅黑"
        run._element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")
        run.font.color.rgb = RGBColor(0x1F, 0x2A, 0x37)
    return p


rows = sorted(RAW["rows"], key=lambda r: (r["kind"], -RAW["eventCounts"].get(r["id"], 0), r["name"]))
counts = RAW["eventCounts"]
total_events = sum(counts.values())
active = [r for r in rows if counts.get(r["id"], 0) > 0]

title = doc.add_heading("Menduner 数据来源清单（爬虫网站）", level=0)
for run in title.runs:
    run.font.name = "微软雅黑"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")

meta = doc.add_paragraph()
meta.add_run("生成时间：").bold = True
meta.add_run(datetime.now().strftime("%Y-%m-%d %H:%M") + "　")
meta.add_run("数据来源：").bold = True
meta.add_run(f"生产库 sources 表实测（共 {len(rows)} 个来源，其中 {len(active)} 个已采集到活动）\n")
meta.add_run("适用项目：").bold = True
meta.add_run("Menduner 城市活动情报平台（ENT303TC 第 14 组）　")
meta.add_run("线上地址：").bold = True
meta.add_run("https://entgroup14.com")

heading("一、总览", 1)
doc.add_paragraph(
    f"平台共登记 {len(rows)} 个数据来源，覆盖政府/官方机构、场馆官网、活动与票务平台、媒体、"
    f"文旅、社区同城、社交媒体七类。所有来源均为公开可访问页面，采集内容为活动的公开信息"
    f"（名称、时间、地点、主办方、原文链接），并按条保存来源链接与采集时间，便于逐条追溯。"
)
doc.add_paragraph(
    f"当前库内按来源归属的活动记录合计 {total_events} 条（同一活动被多个来源收录时会在展示层去重）。"
)

heading("二、来源明细", 1)
table = doc.add_table(rows=1, cols=6)
table.style = "Light Grid Accent 1"
table.alignment = WD_TABLE_ALIGNMENT.CENTER
header = table.rows[0].cells
for index, text in enumerate(["序号", "来源名称", "类型", "网址", "采集活动数", "采集方式"]):
    header[index].text = text
    for paragraph in header[index].paragraphs:
        for run in paragraph.runs:
            run.bold = True
            run.font.size = Pt(9.5)

for index, row in enumerate(rows, start=1):
    cells = table.add_row().cells
    cells[0].text = str(index)
    cells[1].text = row["name"]
    cells[2].text = KIND_LABEL.get(row["kind"], row["kind"])
    cells[3].text = row["source_url"]
    cells[4].text = str(counts.get(row["id"], 0))
    cells[5].text = FLOW.get(row["kind"], "公开页面解析")
    for cell in cells:
        for paragraph in cell.paragraphs:
            for run in paragraph.runs:
                run.font.size = Pt(9)
    # 网址做成可点击
    link_paragraph = cells[3].paragraphs[0]
    link_paragraph.clear() if hasattr(link_paragraph, "clear") else None
    run = link_paragraph.add_run(row["source_url"])
    run.font.size = Pt(8.5)

heading("三、按类型统计", 1)
by_kind = {}
for row in rows:
    by_kind.setdefault(row["kind"], {"sources": 0, "events": 0})
    by_kind[row["kind"]]["sources"] += 1
    by_kind[row["kind"]]["events"] += counts.get(row["id"], 0)

table2 = doc.add_table(rows=1, cols=3)
table2.style = "Light Grid Accent 1"
for index, text in enumerate(["类型", "来源数", "采集活动数"]):
    cell = table2.rows[0].cells[index]
    cell.text = text
    for paragraph in cell.paragraphs:
        for run in paragraph.runs:
            run.bold = True
            run.font.size = Pt(9.5)
for kind, stat in sorted(by_kind.items(), key=lambda item: -item[1]["events"]):
    cells = table2.add_row().cells
    cells[0].text = KIND_LABEL.get(kind, kind)
    cells[1].text = str(stat["sources"])
    cells[2].text = str(stat["events"])
    for cell in cells:
        for paragraph in cell.paragraphs:
            for run in paragraph.runs:
                run.font.size = Pt(9)

heading("四、采集与合规说明", 1)
notes = [
    "只采集公开可访问页面上已发布的活动信息，不绕过登录、不抓取需要授权的内容。",
    "每条活动都保存来源链接与采集时间，平台内可逐条点击回到原文核对（可追溯）。",
    "只保存活动摘要字段（名称、时间、地点、主办方、链接），不转载全文、不复制图片。",
    "小红书来源通过 MediaCrawler 采集公开笔记，仅保留标题、时间、地点与链接，用于补充活动线索。",
    "采集到的活动默认为「未核验」状态；只有经过人工核对字段证据后才会标记为已核验。",
    "平台不采集、不展示酒店房价与经营数据，也不做价格预测或收益预测。",
]
for note in notes:
    doc.add_paragraph(note, style="List Bullet")

heading("五、零采集来源说明", 1)
zero = [row for row in rows if counts.get(row["id"], 0) == 0]
if zero:
    doc.add_paragraph(
        f"下列 {len(zero)} 个来源已登记但当前没有归属活动记录，原因通常是：站点结构调整、"
        f"活动信息以图片或脚本形式发布导致无法解析、或该来源仅用于交叉核对时结果未并入活动表。"
    )
    for row in zero:
        doc.add_paragraph(f"{row['name']}（{row['source_url']}）", style="List Bullet")
else:
    doc.add_paragraph("所有已登记来源均已采集到活动记录。")

heading("六、字段口径", 1)
fields = [
    ("来源标识", "平台内部唯一 id，用于把活动与来源对应起来"),
    ("名称", "来源的对外名称（政府站点、场馆、平台等）"),
    ("类型", "政府/官方、场馆官方、活动与票务平台、媒体、文旅、社区同城、社交媒体"),
    ("网址", "采集入口页地址"),
    ("采集活动数", "当前库内归属于该来源的活动记录条数"),
    ("更新时间", "该来源记录最近一次写入数据库的时间"),
]
table3 = doc.add_table(rows=1, cols=2)
table3.style = "Light Grid Accent 1"
for index, text in enumerate(["字段", "说明"]):
    cell = table3.rows[0].cells[index]
    cell.text = text
    for paragraph in cell.paragraphs:
        for run in paragraph.runs:
            run.bold = True
            run.font.size = Pt(9.5)
for name, desc in fields:
    cells = table3.add_row().cells
    cells[0].text = name
    cells[1].text = desc
    for cell in cells:
        for paragraph in cell.paragraphs:
            for run in paragraph.runs:
                run.font.size = Pt(9)

out = ROOT / "deliverables" / "Menduner数据来源清单.docx"
doc.save(out)
print("  已生成:", out)
print("  来源数:", len(rows), "| 已采集来源:", len(active), "| 活动记录合计:", total_events)
