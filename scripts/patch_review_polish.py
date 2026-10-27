"""按 GPT Round 31（酒店经理身份）的复核意见改审核交互：

1. 「已通过」改为「已人工核对」——避免被误解成整场活动已经核实；
2. 核对后显示「操作人 · 时间」；
3. 顶部显示「已核对 N/3 项」，三项各自确认，不做一键全过。

撤回（第 4 条建议）本轮不做：后端没有"撤回/重开"这个动作，加了会伪造审计语义，
需要先定数据模型，已在汇报中说明。
"""
from pathlib import Path

page = Path(__file__).resolve().parent.parent / "frontend" / "src" / "pages" / "DataQuality" / "index.tsx"
s = page.read_text(encoding="utf-8")

# 1) 记录本地核对痕迹（操作人 + 时间），刷新后可用 evidence.updatedAt 兜底
if "reviewTrail" not in s:
    s = s.replace("  const [quickMsg, setQuickMsg] = useState<string>(\"\");",
                  "  const [quickMsg, setQuickMsg] = useState<string>(\"\");\n"
                  "  // 本次会话内的核对痕迹：字段 -> { 操作人, 时间 }\n"
                  "  const [reviewTrail, setReviewTrail] = useState<Record<string, { who: string; at: string }>>({});")
    s = s.replace('''        setQuickMsg(decision === "Verified" ? "已通过，状态已更新" : "已标记为有问题");''',
'''        setQuickMsg(decision === "Verified" ? "已人工核对，状态已更新" : "已标记为有问题");
        setReviewTrail((current) => ({
          ...current,
          [field]: { who: identity.login ?? "reviewer", at: new Date().toLocaleString("zh-CN") },
        }));''')

# 2) 徽标文案 + 操作人/时间
s = s.replace('if (settled) return <Tag color="green">已通过</Tag>;',
              'if (settled) return <Tag color="green">已人工核对</Tag>;')
s = s.replace('''                  if (pending) return <Tag>待核对</Tag>;''',
'''                  if (pending) return <Tag>待核对</Tag>;''')

if "quick-trail" not in s:
    s = s.replace('''              <span className="quick-actions">''',
'''              <span className="quick-trail">
                {Object.entries(reviewTrail)
                  .filter(([key]) => String(row.field).split("|").includes(key))
                  .map(([key, trace]) => (
                    <small key={key} className="muted">
                      {trace.who} · {trace.at}
                    </small>
                  ))}
              </span>
              <span className="quick-actions">''')

# 3) 标题旁显示已核对计数
if "已核对 " not in s:
    s = s.replace("<strong>快速核对（3 项）</strong>",
                  '''<strong>快速核对（3 项）</strong>
            <span className="muted" style={{ marginLeft: 8 }}>
              已核对{" "}
              {
                [
                  ["name"],
                  ["venueName", "venueId", "venue"],
                  ["sourceUrl"],
                ].filter((names) => !pendingFields.some((item) => names.includes(item.field))).length
              }
              /3 项
            </span>''')

page.write_text(s, encoding="utf-8")
text = page.read_text(encoding="utf-8")
print("  徽标改名:", "已人工核对" in text)
print("  痕迹显示:", "quick-trail" in text)
print("  计数:", "已核对" in text)
