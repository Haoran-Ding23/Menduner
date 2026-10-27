"""审核页加「快速核对（3 项）」：活动名称 / 举办场馆 / 来源链接，一键 ✓ ✗ 过审。

用户的明确要求：只需要核对这三项，每项后面用对号/错号让审核员点击，点对号就通过。

实现要点：
* 复用已有写接口 POST /api/review（需要审核角色），不新增后端逻辑，不改数据结构；
* 点 ✓ → decision=Verified；点 ✗ → decision=Rejected；都带上当前屏幕上看到的值，
  避免"审核员看到的"和"库里存的"不是同一个东西（后端会 409 拒绝，这是既有保护）；
* 只有 canReview 的账号才显示按钮；其余账号看到提示，不给假按钮；
* 提交成功后刷新该活动的字段状态。
"""
from pathlib import Path

page = Path(__file__).resolve().parent.parent / "frontend" / "src" / "pages" / "DataQuality" / "index.tsx"
s = page.read_text(encoding="utf-8")

if "快速核对" not in s:
    # 1) 需要 useCallback
    s = s.replace('import { useMemo, useState } from "react";',
                  'import { useCallback, useMemo, useState } from "react";', 1)

    # 2) 在 reviewer 定义之后插入状态与提交函数
    anchor = "  const dataset = platform.rawDataset ?? platform.dataset;"
    block = anchor + '''
  // 快速核对：只核对三项（活动名称 / 举办场馆 / 来源链接），其余字段仍在下方明细表里
  const [quickBusy, setQuickBusy] = useState<string | null>(null);
  const [quickMsg, setQuickMsg] = useState<string>("");

  const decideField = useCallback(
    async (eventId: string, field: string, value: unknown, decision: "Verified" | "Rejected") => {
      if (!reviewer) return;
      setQuickBusy(field);
      setQuickMsg("");
      try {
        const response = await fetch("/api/review", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            event_id: eventId,
            field,
            decision,
            value: value ?? null,
            reviewer: identity.login ?? "reviewer",
          }),
        });
        if (response.status === 409) {
          setQuickMsg("这条字段在你打开后已变化，请刷新后再核对");
          return;
        }
        if (!response.ok) {
          setQuickMsg("提交失败（需要审核角色或登录已过期）");
          return;
        }
        setQuickMsg(decision === "Verified" ? "已通过" : "已标记为有问题");
        await platform.refresh?.();
      } finally {
        setQuickBusy(null);
      }
    },
    [identity.login, platform, reviewer],
  );
'''
    s = s.replace(anchor, block, 1)

    # 3) 渲染：插在右栏标题行之后（「这一条该怎么处理」那块）
    marker = '        <div className="panel-heading">'
    quick_panel = '''        <div className="quick-check" aria-label="快速核对">
          <div className="quick-check-head">
            <strong>快速核对（3 项）</strong>
            <span className="muted">
              {reviewer ? "点 ✓ 通过、点 ✗ 标记有问题；其余字段在下方明细里" : "需要审核角色才能核对"}
            </span>
          </div>
          {[
            { field: "name", label: "活动名称", value: event?.name },
            {
              field: "venueId",
              label: "举办场馆",
              value:
                dataset.venues.find((v) => v.id === event?.venueId)?.name ??
                (event?.venueId ? "场馆名称待补充" : null),
            },
            { field: "sourceUrl", label: "来源链接", value: event?.sourceUrl },
          ].map((row) => (
            <div className="quick-row" key={row.field}>
              <span className="quick-label">{row.label}</span>
              <span className="quick-value">{row.value ? String(row.value) : "（缺失）"}</span>
              <span className="quick-actions">
                <button
                  type="button"
                  className="quick-btn ok"
                  disabled={!reviewer || quickBusy === row.field || !event}
                  aria-label={row.label + " 通过"}
                  onClick={() => void decideField(event!.id, row.field, row.value, "Verified")}
                >
                  ✓
                </button>
                <button
                  type="button"
                  className="quick-btn no"
                  disabled={!reviewer || quickBusy === row.field || !event}
                  aria-label={row.label + " 有问题"}
                  onClick={() => void decideField(event!.id, row.field, row.value, "Rejected")}
                >
                  ✗
                </button>
              </span>
            </div>
          ))}
          {quickMsg && <p className="muted quick-msg">{quickMsg}</p>}
        </div>

'''
    if marker in s:
        s = s.replace(marker, quick_panel + marker, 1)

    page.write_text(s, encoding="utf-8")

print("  快速核对已插入:", "quick-check" in page.read_text(encoding="utf-8"))
