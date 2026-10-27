"""审核台按酒店服务员视角改写：默认只看「活动名字 / 活动场地 / 来源链接」三项。

用户原话（要点）：不需要看到 name、venueName、venue-ba0119… 这些数据库字段名与内部 ID；
审核时只看中文：活动叫什么、在哪个场地、来源链接点进去核对，然后点 ✓。

实现（纯前端，不改后端与数据结构）：
1. FIELD_LABELS 补齐：name→活动名字、venueName/venue→活动场地、sourceUrl→来源链接；
2. readableValue 扩展：值里出现 venue-/district- 这类内部 ID 时，替换成真实名称；
3. 明细表默认只显示上述三项，另给「显示全部字段」开关，技术字段仍可取用但不默认出现。
"""
from pathlib import Path

page = Path(__file__).resolve().parent.parent / "frontend" / "src" / "pages" / "DataQuality" / "index.tsx"
s = page.read_text(encoding="utf-8")

# 1) 字段名映射补齐
pairs = [
    ('  name: "活动名称",', '  name: "活动名字",'),
    ('  venueId: "举办场馆",', '  venueId: "活动场地",'),
    ('  sourceUrl: "来源链接",', '  sourceUrl: "来源链接",'),
]
for old, new in pairs:
    if old in s:
        s = s.replace(old, new, 1)

if 'venueName: "活动场地"' not in s:
    s = s.replace('  venueId: "活动场地",', '  venueId: "活动场地",\n  venueName: "活动场地",\n  venue: "活动场地",', 1)

# 2) 内部 ID → 名称（venueName / venue 字段也要转换）
if 'field === "venueName" || field === "venue"' not in s:
    s = s.replace('  if (field === "venueId") {',
                  '  if (field === "venueId" || field === "venueName" || field === "venue") {', 1)

# 3) 默认只看三项
if "simpleOnly" not in s:
    anchor = '  const [quickBusy, setQuickBusy] = useState<string | null>(null);'
    s = s.replace(anchor, anchor + '\n  // 酒店服务员视角：默认只核对"活动名字 / 活动场地 / 来源链接"三项\n  const [simpleOnly, setSimpleOnly] = useState(true);', 1)

    s = s.replace("""                <Table<Evidence>
                rowKey="id"
                dataSource={pendingFields}""", """                <Table<Evidence>
                rowKey="id"
                dataSource={
                  simpleOnly
                    ? pendingFields.filter((item) =>
                        ["name", "venueName", "venue", "sourceUrl"].includes(item.field),
                      )
                    : pendingFields
                }""", 1)

    # 表格上方加切换
    s = s.replace("""              <p className="dq-group-title">""", """              <p className="dq-group-title">
                <Button
                  type="link"
                  size="small"
                  style={{ padding: 0, marginRight: 10 }}
                  onClick={() => setSimpleOnly((value) => !value)}
                >
                  {simpleOnly ? "显示全部字段（含技术字段）" : "只看三项（推荐）"}
                </Button>""", 1)

page.write_text(s, encoding="utf-8")
print("  三项默认:", "simpleOnly" in page.read_text(encoding="utf-8"))
print("  字段映射:", 'venueName: "活动场地"' in page.read_text(encoding="utf-8"))
