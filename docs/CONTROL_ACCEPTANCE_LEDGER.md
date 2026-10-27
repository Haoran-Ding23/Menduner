# 控件验收台账（Menduner）

> 目标（用户）：**每一个按钮都要有作用、并且能使用**。
> 标准来源：GPT Round 34 —— 允许的 7 类控件、A/B/C 三档判定、NO-OP=0 只是必要门槛。
> 检测工具：`scripts/cdp-button-audit-v2.mjs`（匿名态逐页点击判定）、
> `scripts/cdp-assertions.mjs`（业务效果断言：点了必须发生什么/不许发生什么）。

## 一、判定口径

| 判定 | 含义 | 是否合格 |
|---|---|---|
| `navigate` | 点击后 URL 变化、到达正确对象 | ✅ A 档 |
| `effect` | DOM 变化 ≥6 / 触发请求 / 出现弹窗 | ✅ 进入 A 档候选，仍需业务断言确认 |
| `disabled` | 控件被禁用 | ⚠️ 仅在"加载中 / 未选对象 / 无权限且已说明"时合格 |
| **`NO-OP`** | 点击后毫无反应 | ❌ 必须修（C 档） |

## 二、已完成的验证（可复跑）

### 1. 匿名态逐页审计（NO-OP）

| 页面 | 控件 | 实测 | NO-OP | 证据文件 |
|---|---|---|---|---|
| 城市活动地图 | 41 | 12–60 | **0** | `deliverables/button-audit.json` |
| 知识图谱 | 17 | 17 | **0** | `deliverables/button-audit-full-1.json` |
| 活动清单 | 135 | 60 | **0** | `deliverables/button-audit-full-1.json` |
| 本店工作台 | 48 | 48 | **0** | `deliverables/button-audit-review.json` |
| 酒店活动情报 | 30 | 30 | **0** | `deliverables/button-audit-review.json` |
| 数据质量与来源 | 3 | 3 | **0** | `deliverables/button-audit-review.json` |
| 商圈洞察 | — | 4 | **0** | `deliverables/button-audit-full-1.json` |
| **审核台** | **93** | **60** | **0** | `deliverables/button-audit-review3.json` |

> 审核台还有 **33 个控件未测到**：无头浏览器在连续点击该页时反复卡死（Page.enable 超时），
> 已在多次重启后仍未跑完。**这 33 个不算通过**，列为待验证。

### 2. 业务效果断言（比 NO-OP 更严，10/10 通过）

`node scripts/cdp-assertions.mjs https://entgroup14.com`

| # | 断言 | 结果 |
|---|---|---|
| 1 | 地图页不自动弹活动详情 | ✅ |
| 2 | 开「查看附近酒店」→ 标记增加，且**视野不变** | ✅ 0→63，zoom 14 不变 |
| 3 | 开「查看商圈」→ 参考点出现，且**视野不变** | ✅ 0→53，zoom 不变 |
| 4 | 商圈洞察点选商圈后**视野不变** | ✅ |
| 5 | 图谱「查看周边设施」能展开 | ✅ 0→4 行 |
| 6 | 图谱「收起周边」能收起 | ✅ 4→0 |
| 7 | 审核台「补录」弹出补录弹窗 | ✅ 标题「补录这个字段」 |
| 8 | 审核台「全部核查完毕」可点 | ✅ disabled=false |
| 9 | 乐观更新：点「对」立即出结果 | ✅ 14ms |
| 10 | 审核台主链路（登录→核对→状态刷新） | ✅ 见 `button-audit-auth.json` |

### 3. 已修掉的"点了没用/用不了"的问题（真实发生过）

| 问题 | 根因 | 状态 |
|---|---|---|
| 字段行 ✓ 提示"需要审核角色" | 点到「缺失」字段返回 404，提示文案误导 | 已修：404 单独解释，缺失字段改为「补录」 |
| 「全部核查完毕」点了没反应 | 按钮要求手填审核人姓名，登录身份不算 | 已修：改用登录身份 |
| 「AI 建议核对」面板看不到 | 权限判断用了手填姓名字段 | 已修：改用登录身份 |
| 打开图层地图会放大/位移 | 每次重绘都 `setFitView` | 已修：只首次自适应，之后保持用户视野 |
| 打开「城市活动地图」只有列表、没地图 | `showMap` 初值 false | 已修：默认地图视图 |
| 切区后仍挂上一区的酒店、视野不动 | 区域变化未重置选择与视野 | 已修：切区清空选中 + refitKey 重新适配 |
| 进地图自动弹出活动详情 | 详情抽屉只看平台状态 | 已修：仅 URL 带 detail 才常驻 |
| 网络抖动把已登录审核员踢出 | `useIdentity` 失败即置匿名 | 已修：失败保留已有身份 |

## 三、待验证 / 待修（不隐瞒）

1. **审核台剩余 33 个控件**：需在稳定环境下补测（脚本已支持 `--cap`，环境修复后可复跑）。
2. **3 条前端测试仍是 skip**：`ui.test` 的证据索引用例、`v12-ui` 两条字段表用例，
   原因是它们通过 `<App>` 挂载，而 App 内部自带 IdentityProvider 会覆盖注入的 reviewer 身份；
   需要让 App 支持传入身份，或在测试里 stub `/api/auth/me`。
3. **审计脚本自身曾三次出错**（已记录，避免重犯）：
   - 页面清单缺 `/review` → "0 NO-OP" 是空跑；
   - 破坏性跳过定义了但没调用 → 误点「生成建议」，生产多 7 条建议；
   - 跳过正则没处理「通 过 / 驳 回 / 修 正」的空格 → 差点写入审核动作（已确认未写入）。

## 四、复跑方式

```bash
# 逐页 NO-OP 审计（匿名态，自动跳过写入类按钮）
node scripts/cdp-button-audit-v2.mjs https://entgroup14.com --cap 95 --json out.json

# 业务效果断言（10 项）
node scripts/cdp-assertions.mjs https://entgroup14.com

# 地图视野探针 / 移动端逐页检查
node scripts/cdp-map-verify.mjs <url> <lng> <lat>
node scripts/cdp-mobile-audit.mjs https://entgroup14.com
```
