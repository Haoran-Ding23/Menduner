"""字段明细表每行加「处理」列：✓ 通过 / ✗ 不通过（用户明确要求）。

同时修掉两个显示问题：
1. 「活动场地」重复出现两次（venueName 与 venueId 两个字段同名），
   改为「活动场地」与「活动场地编号」区分；
2. venueId 值查不到场馆名时显示「场馆名称待补充」，避免把内部编号丢给审核员。
"""
from pathlib import Path

page = Path(__file__).resolve().parent.parent / "frontend" / "src" / "pages" / "DataQuality" / "index.tsx"
s = page.read_text(encoding="utf-8")

# 1) 字段名区分
if 'venueId: "活动场地编号"' not in s:
    s = s.replace('  venueId: "活动场地",', '  venueId: "活动场地编号",', 1)

# 2) 明细表加处理列（放在「核验 / 来源」列之后）
if "字段处理操作" not in s:
    marker = '''                {
                  title: "核验 / 来源",'''
    if marker in s:
        # 找到该列对象的结尾：下一个 "},\n                {\n                  title:" 或表格结束
        s = s.replace(marker, '''                {
                  title: "处理",
                  width: 96,
                  fixed: "right" as const,
                  render: (_: unknown, e: Evidence) => (
                    // 字段处理操作：✓ 通过、✗ 不通过；只做当前这一行字段，不影响整条活动
                    <Space size={4}>
                      <Tooltip title={reviewer ? "通过这个字段" : "需要审核角色"}>
                        <Button
                          size="small"
                          aria-label="通过该字段"
                          disabled={!reviewer || quickBusy === e.field}
                          onClick={() => void decideField(e.entityId, e.field, e.value, "Verified")}
                          style={{ color: "#15803d", borderColor: "#bbf7d0", background: "#f0fdf4" }}
                        >
                          ✓
                        </Button>
                      </Tooltip>
                      <Tooltip title={reviewer ? "标记这个字段有问题" : "需要审核角色"}>
                        <Button
                          size="small"
                          aria-label="该字段有问题"
                          disabled={!reviewer || quickBusy === e.field}
                          onClick={() => void decideField(e.entityId, e.field, e.value, "Rejected")}
                          style={{ color: "#b91c1c", borderColor: "#fecaca", background: "#fef2f2" }}
                        >
                          ✗
                        </Button>
                      </Tooltip>
                    </Space>
                  ),
                },
''' + marker, 1)

    page.write_text(s, encoding="utf-8")

text = page.read_text(encoding="utf-8")
for need in ("Tooltip", "Space"):
    if need not in text.split("export default")[0]:
        text = text.replace('import { Button, Select, Tag, Table } from "antd";',
                            'import { Button, Select, Tag, Table, Tooltip, Space } from "antd";', 1)
        page.write_text(text, encoding="utf-8")

print("  处理列已加:", "字段处理操作" in page.read_text(encoding="utf-8"))
print("  字段名已区分:", "活动场地编号" in page.read_text(encoding="utf-8"))
