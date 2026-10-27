"""把 AI 解读卡片挂到商圈洞察（画像区块之后），并补样式。"""
from pathlib import Path

root = Path(__file__).resolve().parent.parent
page = root / "frontend" / "src" / "pages" / "DistrictInsights" / "index.tsx"
s = page.read_text(encoding="utf-8")

if "AiMarketCard" not in s:
    s = s.replace('import EmptyHint from "../../components/EmptyHint";',
                  'import AiMarketCard from "../../components/AiMarketCard";\n'
                  'import EmptyHint from "../../components/EmptyHint";', 1)
    anchor = '      {/* 明细与口径 */}'
    block = '''      {/* AI 解读：证据约束型，明确标注未经核实 */}
      <AiMarketCard
        areaId={selected}
        radius={radius}
        start={monthWindow.start}
        end={monthWindow.end}
      />

''' + anchor
    s = s.replace(anchor, block, 1)
    page.write_text(s, encoding="utf-8")

css = '''

/* AI 商圈解读卡片 */
.ai-card { margin-bottom: 16px; }
.ai-summary { font-size: 14px; line-height: 22px; color: #0f172a; margin: 4px 0 8px; }
.ai-findings { margin: 0 0 8px; padding-left: 18px; font-size: 13px; line-height: 1.9; color: #0f172a; }
.ai-metric-keys { margin-left: 6px; display: inline-flex; gap: 4px; flex-wrap: wrap; }
.ai-metric-keys code {
  font-size: 11px; color: #475569; background: #f1f5f9;
  border-radius: 4px; padding: 1px 5px;
}
.ai-rejected { margin: 0 0 8px; padding-left: 18px; font-size: 12px; color: #92400e; line-height: 1.8; }
'''
style = root / "frontend" / "src" / "styles" / "global.css"
style.write_text(style.read_text(encoding="utf-8") + css, encoding="utf-8")

print("  已挂载:", "AiMarketCard" in page.read_text(encoding="utf-8"))
