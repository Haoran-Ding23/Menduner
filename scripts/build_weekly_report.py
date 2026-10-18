"""Build one pilot weekly report (HTML + PDF-ready + Excel detail).

The report is deliberately narrow. Only events the editor can justify in one sentence go into the
"worth watching" table; every other nearby event is still listed, but as a plain list, not padded
into the focus table. Relevance and reliability are separate columns, the window definitions are
written into the report, and the first issue is a baseline with no change comparison.

Editorial judgement is an input, not generated: pass ``--notes`` with the reasons for the events
worth watching. If no reasons are given, nothing is promoted into the focus table and the report
says so — the alternative (auto-promoting events) is how a report starts inventing relevance.

Usage:
  python scripts/build_weekly_report.py \
    --hotel 苏州洲际酒店 --week-start 2026-10-19 \
    --notes docs/pilot/weekly-notes-2026-W43.json

PDF is printed from the generated HTML with a headless browser:
  msedge --headless=new --no-pdf-header-footer --print-to-pdf=<out>.pdf <out>.html
"""
from __future__ import annotations

import argparse
import html
import json
import math
import sys
import urllib.request
from datetime import date, timedelta
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

URL = "http://47.116.133.230/api/dataset"
TODAY = date.today()
HOTEL = "苏州洲际酒店"
OUTER_KM = 3.0
OUT_DIR = Path("docs/pilot")
WEEK_START: date = date.today()
OFFICIAL_KINDS = {"government", "venue"}

# Filled from --notes by main(). Kept module-level because the report writers below read them.
NOTES: dict[str, dict[str, str]] = {}
LONG_RUNNING_IDS: set[str] = set()


def load_notes(path: str | None) -> tuple[dict[str, dict[str, str]], set[str]]:
    """Editorial input: which events are worth watching, and why."""
    if not path:
        return {}, set()
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    notes = document.get("notes") or {}
    if not isinstance(notes, dict):
        raise SystemExit(f"{path}: 'notes' must be an object keyed by event id")
    long_running = document.get("longRunningIds") or []
    return notes, set(long_running)



def parse(day):
    try:
        return date.fromisoformat((day or "")[:10])
    except ValueError:
        return None


def km(a, b):
    lng1, lat1 = float(a["lng"]), float(a["lat"])
    lng2, lat2 = float(b["lng"]), float(b["lat"])
    radius = 6371.0
    dlat, dlng = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    h = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(
        math.radians(lat2)) * math.sin(dlng / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(h))


def fetch():
    with urllib.request.urlopen(URL, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def gather():
    data = fetch()
    venues = {v["id"]: v for v in data["venues"]}
    source_kinds = {s["id"]: s["kind"] for s in data["status"]["sources"]}
    source_names = {s["id"]: s["name"] for s in data["status"]["sources"]}
    evidence: dict[str, list] = {}
    for row in data["evidence"]:
        evidence.setdefault(row["entityId"], []).append(row)
    hotel = next(h for h in data["hotels"] if h["name"] == HOTEL)
    anchor = hotel["coordinates"]

    week_start = WEEK_START
    week_end = week_start + timedelta(days=6)
    horizon30 = week_start + timedelta(days=29)

    rows = []
    for event in data["events"]:
        if event.get("demo"):
            continue
        start = parse(event.get("startDate"))
        if not start:
            continue
        end = parse(event.get("endDate")) or start
        venue = venues.get(event.get("venueId"))
        coordinates = (venue or {}).get("coordinates")
        if not coordinates:
            continue
        distance = km(anchor, coordinates)
        if distance > OUTER_KM:
            continue
        if not (start < TODAY and end >= TODAY) and not (TODAY <= start <= horizon30):
            continue
        claims = evidence.get(event["id"], [])
        rows.append({
            "id": event["id"],
            "name": event["name"],
            "start": start,
            "end": end,
            "days": (end - start).days + 1,
            "venue": event.get("venueName") or venue.get("name"),
            "distance": distance,
            "category": event.get("category"),
            "source": event.get("source"),
            "sourceKind": source_kinds.get(event.get("source"), "other"),
            "sourceName": source_names.get(event.get("source")),
            "sourceUrl": event.get("sourceUrl") or (claims[0].get("sourceUrl") if claims else None),
            "status": event.get("verification_status"),
            "claims": len(claims),
            "inWeek": week_start <= start <= week_end,
            "in30": week_start <= start <= horizon30,
            "longRunning": event["id"] in LONG_RUNNING_IDS,
        })
    rows.sort(key=lambda r: (r["start"], r["distance"]))
    city_starts = sum(
        1 for e in data["events"]
        if not e.get("demo") and parse(e.get("startDate"))
        and TODAY <= parse(e.get("startDate")) <= horizon30
    )
    return {
        "hotel": hotel,
        "rows": rows,
        "week": (week_start, week_end),
        "horizon30": horizon30,
        "revision": data["status"]["revision"],
        "eventCount": len(data["events"]),
        "cityStarts": city_starts,
    }


def sections(context):
    rows = context["rows"]
    focus = [r for r in rows if r["inWeek"] and r["days"] >= 2 and r["id"] in NOTES]
    others_week = [r for r in rows if r["inWeek"] and r["id"] not in NOTES]
    future = [r for r in rows if r["in30"] and not r["inWeek"] and r["id"] not in LONG_RUNNING_IDS]
    # The advance-planning table is for business/exhibition/sport events: a wall of 1–3 day
    # theatre runs is what the appendix is for. Culture stays visible as a count, not as rows.
    future_business = [r for r in future if r["days"] >= 2 and r["category"] != "culture"]
    future_culture = [r for r in future if r["category"] == "culture"]
    long_running = [r for r in rows if r["longRunning"]]
    return focus, others_week, future_business, future_culture, long_running


def source_label(row):
    return "场馆/官方" if row["sourceKind"] in OFFICIAL_KINDS else "第三方平台"


def html_report(context):
    week_start, week_end = context["week"]
    focus, others_week, future_business, future_culture, long_running = sections(context)
    total_week = len(focus) + len(others_week)
    iso = week_start.isocalendar()
    title = f"Menduner 酒店活动周报 · {HOTEL} · 第 1 期(基线)"
    subtitle = (f"覆盖周期 {week_start.isoformat()} 至 {week_end.isoformat()}(周一至周日) · "
                f"数据截至 {TODAY.isoformat()} · Asia/Shanghai · ISO {iso.year}-W{iso.week:02d}")

    def focus_row(row, index):
        note = NOTES[row["id"]]
        reliability = (f"来源:{row['sourceName'] or row['source']}({source_label(row)});"
                       f"事件状态:{row['status']};字段证据 {row['claims']} 条")
        source_url = row["sourceUrl"] or ""
        return f"""
        <tr>
          <td class="num">{index}</td>
          <td><b>{html.escape(row['name'])}</b><br>
              <span class="src">{html.escape(row['venue'] or '场馆未记录')} ·
              {row['start'].isoformat()} → {row['end'].isoformat()} · {row['days']} 天</span><br>
              <span class="src">{html.escape(source_url)[:78]}</span></td>
          <td class="num">{row['distance']:.2f} km</td>
          <td>{html.escape(note['reason'])}<br>
              <span class="src">类别:{html.escape(note['categoryReview'])}</span></td>
          <td>{html.escape(reliability)}</td>
          <td>{html.escape(note['action'])}</td>
        </tr>"""

    focus_rows = "".join(focus_row(r, i + 1) for i, r in enumerate(focus))
    others_rows = "".join(
        f"<tr><td>{html.escape(r['name'])}</td><td class='num'>{r['start'].isoformat()}</td>"
        f"<td class='num'>{r['days']}</td><td class='num'>{r['distance']:.2f} km</td></tr>"
        for r in others_week[:12]
    )
    future_rows = "".join(
        f"<tr><td class='num'>{i + 1}</td><td>{html.escape(r['name'])}</td>"
        f"<td class='num'>{r['start'].isoformat()}</td><td class='num'>{r['days']}</td>"
        f"<td class='num'>{r['distance']:.2f} km</td><td>{source_label(r)}</td></tr>"
        for i, r in enumerate(future_business[:10])
    )
    long_rows = "".join(
        f"<tr><td>{html.escape(r['name'])}</td><td class='num'>{r['start'].isoformat()}</td>"
        f"<td class='num'>{r['end'].isoformat()}</td><td class='num'>{r['days']} 天</td></tr>"
        for r in long_running[:6]
    )

    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>{html.escape(title)}</title>
<style>
  @page {{ size: A4; margin: 11mm 11mm 9mm 11mm; }}
  body {{ font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans SC", sans-serif;
          font-size: 9pt; color: #1f2328; line-height: 1.4; }}
  h1 {{ font-size: 14.5pt; margin: 0 0 1.5mm 0; }}
  h2 {{ font-size: 10.2pt; margin: 3.4mm 0 1.2mm 0; border-left: 3px solid #1677ff;
        padding-left: 2.4mm; }}
  .sub {{ color: #57606a; font-size: 8.2pt; margin-bottom: 2.5mm; }}
  .lead {{ background: #f6f8fa; border: 1px solid #d0d7de; border-radius: 2mm;
           padding: 2.2mm 2.8mm; margin: 1.5mm 0 2.5mm 0; }}
  .lead b {{ color: #0b4f9e; }}
  table {{ width: 100%; border-collapse: collapse; margin: 0.8mm 0 1.8mm 0; }}
  th {{ background: #eef3fb; text-align: left; font-weight: 600; font-size: 8.2pt;
        border: 1px solid #c9d4e3; padding: 1.2mm; }}
  td {{ border: 1px solid #d8dee7; padding: 1.2mm; vertical-align: top; }}
  td.num {{ white-space: nowrap; }}
  .src {{ color: #57606a; font-size: 7.4pt; word-break: break-all; }}
  .note {{ font-size: 7.8pt; color: #57606a; }}
  ul {{ margin: 0.8mm 0 1.8mm 4mm; padding: 0; }}
  li {{ margin: 0.7mm 0; }}
  .foot {{ margin-top: 3mm; border-top: 1px solid #d0d7de; padding-top: 1.6mm;
           font-size: 7.6pt; color: #57606a; }}
  .pagebreak {{ page-break-before: always; }}
</style></head><body>
<h1>{html.escape(title)}</h1>
<div class="sub">{html.escape(subtitle)} · 数据源:线上数据集 revision {context['revision']}
({context['eventCount']} 场活动,其中未来 30 天全市新开场 {context['cityStarts']} 场) ·
半径 {OUTER_KM:.0f} km</div>

<div class="lead">
  <b>本期要点</b>
  <ul>
    <li>本酒店 3 km 内、本周期内新开场 <b>{total_week} 场</b>,其中 <b>{len(focus)} 场</b>达到“值得关注”
        标准(2 天以上、可写出具体理由),全部在苏州国际博览中心(距酒店约 0.56 km)。</li>
    <li>本周为第 1 期,<b>只建立基线,不做变化对比</b>;下一期开始记录新活动、改期、场馆变化与取消。</li>
    <li>邻近 ≠ 住宿需求:库内<b>没有活动人数、入住率、房价数据</b>。“值得关注”是相关性判断,
        每条都写了理由;是否跟进请以你核实到的规模为准。</li>
    <li>类别由爬虫自动归类,本期人工复核了 {len(focus)} 条(见每行“类别”)。</li>
  </ul>
</div>

<h2>一、本期值得关注({len(focus)} 场,逐条说明为什么)</h2>
<table>
  <thead><tr>
    <th style="width:4%">#</th><th style="width:26%">活动 / 场馆 / 日期</th>
    <th style="width:8%">直线距离</th><th style="width:27%">相关性:为什么值得关注(含依据)</th>
    <th style="width:19%">可靠性(与相关性分开看)</th><th style="width:16%">建议动作</th>
  </tr></thead>
  <tbody>{focus_rows}</tbody>
</table>
<div class="note">只写达到标准的 {len(focus)} 场,不凑数。其余本周与 3 km 内的活动见下表,
它们不是“不值得看”,而是没有足够依据写出一条具体的关注理由,因此不进入本期重点。</div>

<h2>二、本周其余邻近活动({len(others_week)} 场,仅列出)</h2>
<table>
  <thead><tr><th style="width:64%">活动</th><th style="width:14%">开始</th>
    <th style="width:8%">天数</th><th style="width:14%">直线距离</th></tr></thead>
  <tbody>{others_rows}</tbody>
</table>

<h2>三、未来 30 天内将开场的会展/赛事类活动(10-26 起,供提前安排)</h2>
<table>
  <thead><tr><th style="width:4%">#</th><th style="width:44%">活动</th><th style="width:13%">开始</th>
    <th style="width:7%">天数</th><th style="width:12%">直线距离</th><th style="width:20%">来源</th></tr></thead>
  <tbody>{future_rows}</tbody>
</table>
<div class="note">本表只列 2 天以上的会展/赛事/其他类活动;另有 {len(future_culture)} 场演出类活动
(1–3 天,以苏州文化艺术中心为主)未逐条列出,全部明细见 Excel。同一活动可能在两个来源各有一条
记录(如汽车工程学会年会),尚未合并,请以场馆官网为准。</div>

<h2>四、与本期重叠、但不是本周新开场的活动(长期展览)</h2>
<table>
  <thead><tr><th style="width:52%">活动</th><th style="width:16%">开始</th>
    <th style="width:16%">结束</th><th style="width:16%">持续</th></tr></thead>
  <tbody>{long_rows}</tbody>
</table>
<div class="note">这些活动在窗口开始时已经在展,不构成“新增”信号;要判断客流需要另外的依据。</div>

<h2>五、变化(第 1 期:基线)</h2>
<ul>
  <li>本期<b>无上一期可比</b>。从第 2 期开始记录:首次发现 / 日期变化 / 场馆变化 /
      来源明确取消 / 未再检出(待核实)。</li>
  <li>采集失败或来源列表临时删除<b>不会</b>直接标记为取消;需要连续未检出且来源采集正常才提示核实。</li>
</ul>

<h2>六、数据说明(口径与已知问题)</h2>
<ul>
  <li><b>窗口</b>:{week_start.isoformat()} 至 {week_end.isoformat()}(Asia/Shanghai,周一至周日);
      “新开场”= 开始日期落在窗口内;“重叠”= 开始日期早于窗口且结束日期不早于窗口。</li>
  <li><b>距离</b>:GCJ-02 坐标上的 haversine 大圆距离,不是道路/步行距离;半径 {OUTER_KM:.0f} km。</li>
  <li><b>可靠性</b>:来源类型(场馆官网/政府 vs 第三方平台)+ 事件状态 + 字段证据条数;
      原始链接见每条活动与 Excel 明细。</li>
  <li><b>已知问题</b>:(1) 类别自动归类有误判(本期已复核);(2) 同一活动多来源未合并;
      (3) 无活动人数、住宿需求、入住率、房价数据,本报告不做需求或收入预测。</li>
  <li><b>口径版本</b>:2026-10-18 第 1 版;口径调整会在下一期注明。</li>
</ul>

<div class="foot">
  Menduner · 城市活动情报 · 试点评估材料,不构成任何收入或入住率预测。
  生成时间 {TODAY.isoformat()} · 数据 revision {context['revision']} · 示例酒店 {HOTEL}
</div>
</body></html>"""


def excel_report(context):
    week_start, week_end = context["week"]
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "本期活动明细"
    headers = ["#", "开始日期", "结束日期", "天数", "活动名称", "场馆", "距酒店(km)",
               "类别(爬虫)", "类别(人工复核)", "来源类型", "来源名称", "来源链接",
               "事件状态", "字段证据", "窗口内新开场", "未来30天", "入选本期重点",
               "相关性理由", "可靠性说明", "建议动作", "人工复核意见", "变化状态(第1期)",
               "客户反馈"]
    sheet.append(headers)
    for index, row in enumerate(context["rows"], start=1):
        note = NOTES.get(row["id"], {})
        sheet.append([
            index, row["start"].isoformat(), row["end"].isoformat(), row["days"], row["name"],
            row["venue"], round(row["distance"], 2), row["category"],
            note.get("categoryReview", ""), source_label(row), row["sourceName"],
            row["sourceUrl"], row["status"], row["claims"],
            "是" if row["inWeek"] else "否", "是" if row["in30"] else "否",
            "是" if row["id"] in NOTES else "否",
            note.get("reason", ""), f"来源类型 + 事件状态 + {row['claims']} 条字段证据",
            note.get("action", ""), "", "首次发现(基线)", "",
        ])
    widths = [4, 11, 11, 5, 34, 20, 9, 9, 22, 10, 20, 46, 11, 7, 9, 9, 9, 40, 30, 34, 20, 14, 24]
    for position, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(position)].width = width
    header_fill = PatternFill("solid", fgColor="EEF3FB")
    thin = Side(style="thin", color="C9D4E3")
    for cell in sheet[1]:
        cell.font = Font(bold=True, size=10)
        cell.fill = header_fill
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        cell.border = Border(bottom=thin)
    for row_cells in sheet.iter_rows(min_row=2):
        for cell in row_cells:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    sheet.freeze_panes = "A2"

    meta = workbook.create_sheet("口径与说明")
    meta.append(["项目", "值"])
    for key, value in [
        ("覆盖周期", f"{week_start.isoformat()} ~ {week_end.isoformat()} (Asia/Shanghai)"),
        ("示例酒店", HOTEL),
        ("数据源", f"线上数据集 revision {context['revision']};{context['eventCount']} 场活动"),
        ("半径", f"{OUTER_KM:.0f} km(GCJ-02 haversine 大圆距离,非道路距离)"),
        ("窗口定义", "新开场 = 开始日期在窗口内;重叠 = 开始日期早于窗口且结束日期不早于窗口"),
        ("入选规则", "窗口内新开场、持续 2 天以上、3 km 内、非 demo,且能写出一条具体关注理由"),
        ("不凑数", "达到标准几条就写几条;其余活动仍列出,但不进入“本期重点”"),
        ("无数据项", "活动人数、住宿需求、入住率、房价——本报告不做需求或收入预测"),
        ("已知问题", "类别自动归类有误判;同一活动多来源未合并;变化对比从第 2 期开始"),
        ("口径版本", "2026-10-18 第 1 版"),
    ]:
        meta.append([key, value])
    meta.column_dimensions["A"].width = 16
    meta.column_dimensions["B"].width = 96
    for row_cells in meta.iter_rows():
        for cell in row_cells:
            cell.alignment = Alignment(wrap_text=True, vertical="top")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    xlsx = OUT_DIR / "menduner-zhouji-2026-W43.xlsx"
    workbook.save(xlsx)
    return xlsx


def main(argv: list[str] | None = None) -> int:
    global TODAY, HOTEL, OUTER_KM, OUT_DIR, URL, NOTES, LONG_RUNNING_IDS, WEEK_START
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hotel", default=HOTEL, help="酒店全名(与数据集里的 name 完全一致)")
    parser.add_argument("--week-start", default=None, help="周一日期 YYYY-MM-DD;默认下一个周一")
    parser.add_argument("--radius-km", type=float, default=OUTER_KM)
    parser.add_argument("--notes", default=None, help="编辑判断 JSON(活动 id → 理由/复核/建议)")
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    parser.add_argument("--api", default=URL, help="数据集地址")
    parser.add_argument("--today", default=None, help="量统计的窗口起点(默认今天)")
    args = parser.parse_args(argv)

    URL = args.api
    OUT_DIR = Path(args.out_dir)
    OUTER_KM = args.radius_km
    TODAY = date.fromisoformat(args.today) if args.today else date.today()
    HOTEL = args.hotel
    WEEK_START = (
        date.fromisoformat(args.week_start)
        if args.week_start
        else TODAY + timedelta(days=(7 - TODAY.weekday()) % 7)
    )
    if WEEK_START.weekday() != 0:
        raise SystemExit(f"--week-start must be a Monday, got {WEEK_START} ({WEEK_START:%A})")
    NOTES, LONG_RUNNING_IDS = load_notes(args.notes)

    context = gather()
    week_start, week_end = context["week"]
    iso = week_start.isocalendar()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    html_path = OUT_DIR / f"menduner-zhouji-{iso.year}-W{iso.week:02d}.html"
    html_path.write_text(html_report(context), encoding="utf-8")
    xlsx_path = excel_report(context)
    focus, others_week, future_business, future_culture, long_running = sections(context)
    print(f"hotel: {HOTEL}  week: {week_start} .. {week_end}  (ISO {iso.year}-W{iso.week:02d})")
    print(f"focus: {len(focus)}  others-week: {len(others_week)}  "
          f"future-business: {len(future_business)}  future-culture: {len(future_culture)}  "
          f"long-running: {len(long_running)}  excel rows: {len(context['rows'])}")
    print("focus ids:", [(r["id"], r["name"][:20]) for r in focus])
    print("html :", html_path, html_path.stat().st_size, "bytes")
    print("xlsx :", xlsx_path, xlsx_path.stat().st_size, "bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
