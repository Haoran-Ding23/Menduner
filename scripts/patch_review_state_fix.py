"""修正快速核对的状态判定。

错误上一版：直接用 evidence 的 effectiveStatus 判断 → name 字段的 evidence 多为自动核验，
于是每一条活动都显示"已通过"且按钮永远禁用。

正确做法：用页面既有的两份列表判断——
  pendingFields（待处理）→ 待核对，可点；
  settledFields（已核验）→ 已通过，禁用。
这样"点完之后变化"就与审核台实际口径一致。
"""
from pathlib import Path

page = Path(__file__).resolve().parent.parent / "frontend" / "src" / "pages" / "DataQuality" / "index.tsx"
s = page.read_text(encoding="utf-8")

start = s.find('              <span className="quick-status">')
end = s.find('              <span className="quick-actions">', start)
if start > 0 and end > start:
    replacement = '''              <span className="quick-status">
                {(() => {
                  // 与审核台同一口径：待处理=可点；已核验=已通过；都没有=无记录
                  const names = String(row.field).split("|");
                  const pending = pendingFields.some((item) => names.includes(item.field));
                  if (pending) return <Tag>待核对</Tag>;
                  const settled = settledFields.some((item) => names.includes(item.field));
                  if (settled) return <Tag color="green">已通过</Tag>;
                  return <Tag>无记录</Tag>;
                })()}
              </span>
'''
    s = s[:start] + replacement + s[end:]

# 按钮可用性同样基于待处理列表
import re
s = re.sub(
    r"disabled=\{\s*\(\(\) => \{.*?\}\)\(\)\s*\}",
    'disabled={\n                    !reviewer ||\n                    quickBusy === row.field ||\n                    !event ||\n                    !pendingFields.some((item) => row.field.split("|").includes(item.field))\n                  }',
    s,
    count=1,
    flags=re.S,
)

# 快速核对三行改为支持多字段名（场馆既有 venueName 也有 venueId）
s = s.replace('{ field: "name", label: "活动名字", value: event?.name },',
              '{ field: "name", label: "活动名字", value: event?.name },')
s = s.replace('''            {
              field: "venueId",
              label: "举办场馆",''',
'''            {
              field: "venueName|venueId|venue",
              label: "举办场馆",''')

page.write_text(s, encoding="utf-8")
text = page.read_text(encoding="utf-8")
print("  状态判定已改为列表口径:", "pendingFields.some((item) => names.includes(item.field))" in text)
print("  按钮禁用基于待处理:", '!pendingFields.some((item) => row.field.split("|")' in text)
