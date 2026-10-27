"""修「点完对号只是变暗一下，没有别的效果」。

根因：POST /api/review 成功后没有重新拉取数据。页面上的核验状态来自 dataset 快照
（evidence 的 effectiveStatus），不刷新就永远显示"待复核"。
上一轮我删掉了 platform.refresh（不存在），但平台其实提供 reloadData()。

改法：
1. 提交成功后调用 platform.reloadData()，字段状态、待处理计数、已核验列表随之更新；
2. 三行快速核对每行显示当前状态（待核对 / 已通过 / 有问题），已通过就禁用按钮，
   不再让人反复点同一个字段；
3. 失败时保留错误提示，不静默。
"""
from pathlib import Path

page = Path(__file__).resolve().parent.parent / "frontend" / "src" / "pages" / "DataQuality" / "index.tsx"
s = page.read_text(encoding="utf-8")

# 1) 提交后刷新数据
if "reloadData" not in s:
    s = s.replace("const { dataset, allEvents, filters, update } = usePlatform();",
                  "const { dataset, allEvents, filters, update } = usePlatform();", 1)
    s = s.replace('''        setQuickMsg(decision === "Verified" ? "已通过" : "已标记为有问题");''',
'''        setQuickMsg(decision === "Verified" ? "已通过，状态已更新" : "已标记为有问题");
        // 关键：重新拉取数据，否则页面仍显示"待复核"（用户看到的"闪一下就恢复"就是这个）
        await reloadData();''')
    s = s.replace("  const [simpleOnly, setSimpleOnly] = useState(true);",
                  "  const [simpleOnly, setSimpleOnly] = useState(true);\n  const { reloadData } = platform;")
    s = s.replace("    [identity.login, platform, reviewer],",
                  "    [identity.login, platform, reloadData, reviewer],")

# 2) 快速核对每行显示状态徽标，已验证则禁用
if 'quick-status' not in s:
    s = s.replace('''          {[
            { field: "name", label: "活动名字", value: event?.name },''',
'''          {[
            { field: "name", label: "活动名字", value: event?.name },''')
    s = s.replace('''              <span className="quick-actions">''',
'''              <span className="quick-status">
                {(() => {
                  const record = dataset.evidence.find(
                    (item) => item.entityId === event?.id && item.field === row.field,
                  );
                  const state = record ? effectiveStatus(record) : "Unknown";
                  if (state === "Verified") return <Tag color="green">已通过</Tag>;
                  if (state === "Rejected") return <Tag color="red">有问题</Tag>;
                  if (state === "Conflicting") return <Tag color="orange">来源冲突</Tag>;
                  return <Tag>待核对</Tag>;
                })()}
              </span>
              <span className="quick-actions">''')
    # 已验证的字段禁用按钮
    s = s.replace('disabled={!reviewer || quickBusy === row.field || !event}',
                  'disabled={\n                    !reviewer ||\n                    quickBusy === row.field ||\n                    !event ||\n                    effectiveStatus(\n                      dataset.evidence.find(\n                        (item) => item.entityId === event?.id && item.field === row.field,\n                      ) ?? { field: row.field, status: "Unknown" },\n                    ) === "Verified"\n                  }')

page.write_text(s, encoding="utf-8")
text = page.read_text(encoding="utf-8")
print("  已调用 reloadData:", "await reloadData()" in text)
print("  状态徽标:", "quick-status" in text)
