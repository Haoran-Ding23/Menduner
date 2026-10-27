"""删掉顶部「快速核对（3 项）」，并让表格行内 ✓/✗ 有明确反馈。

用户反馈（两条）：
1. 快速核对那块删掉（和下面表格重复）；
2. 表格里的 ✓ / ✗「完全没有任何的反馈」——点了看不到结果。

改法：
- 删除 quick-check 整块 JSX（含状态计数、痕迹显示、quickMsg）；
- 行内 ✓/✗ 用 antd message 弹提示（成功/失败/需重新核对），并且提交后 reloadData，
  行会因状态变化而移出"待处理"或改徽标，形成可见结果；
- 提交中把该行按钮禁用，避免重复点。
"""
from pathlib import Path

page = Path(__file__).resolve().parent.parent / "frontend" / "src" / "pages" / "DataQuality" / "index.tsx"
lines = page.read_text(encoding="utf-8").splitlines(True)

start = next(i for i, line in enumerate(lines) if 'className="quick-check"' in line)
# 结束：紧随其后的、缩进为 8 空格的 </div>
end = start
while end < len(lines) and lines[end].strip() != "</div>":
    end += 1
# 再跳过紧跟的一个空行
removed = end - start + 1
del lines[start:end + 1]
page.write_text("".join(lines), encoding="utf-8")
print(f"  已删除快速核对区块（{removed} 行）")

s = page.read_text(encoding="utf-8")

# 用 message 提供可见反馈
if "message.success" not in s:
    s = s.replace('import { Alert, Button, Input, Select, Space, Switch, Table, Tag, Tooltip } from "antd";',
                  'import { Alert, App, Button, Input, Select, Space, Switch, Table, Tag, Tooltip } from "antd";', 1)
    s = s.replace("  const [quickBusy, setQuickBusy] = useState<string | null>(null);",
                  "  const [quickBusy, setQuickBusy] = useState<string | null>(null);\n  const { message } = App.useApp();", 1)
    s = s.replace('''      setQuickBusy(field);
      setQuickMsg("");''',
'''      setQuickBusy(field);''')
    s = s.replace('''        if (response.status === 409) {
          setQuickMsg("这条字段在你打开后已变化，请刷新后再核对");
          return;
        }
        if (!response.ok) {
          setQuickMsg("提交失败（需要审核角色或登录已过期）");
          return;
        }
        setQuickMsg(decision === "Verified" ? "已人工核对，状态已更新" : "已标记为有问题");''',
'''        if (response.status === 409) {
          message.warning("这条字段在你打开后已变化，请刷新后再核对");
          return;
        }
        if (!response.ok) {
          message.error("提交失败：需要审核角色，或登录已过期");
          return;
        }
        message.success(
          decision === "Verified" ? "已人工核对：" + String(field) : "已标记有问题：" + String(field),
        );''')
    s = s.replace("    [identity.login, platform, reloadData, reviewer],",
                  "    [identity.login, message, platform, reloadData, reviewer],")

page.write_text(s, encoding="utf-8")
text = page.read_text(encoding="utf-8")
print("  message 反馈已加:", "message.success" in text)
print("  快速核对已移除:", "quick-check" not in text)
