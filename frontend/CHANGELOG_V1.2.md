# Frontend V1.2 — City Event Intelligence

基线：V1.1 提交 `282f80f`。本次是既有前端的增量调整，没有重建工程、添加后端或改变本地 JSON 适配器。

## 六页主要变化与用途

| 页面 | 主要界面变化 | 使用价值 |
|---|---|---|
| /map | Attention 标签；详情解释类别、持续时间、酒店资源与场馆信息；证据分离核验；酒店资源点与连线 | 回答活动在哪里、为何值得关注，以及附近有哪些已配置酒店 |
| /calendar | Important Event Period 卡片与日历高亮；逐段说明活动重叠、商务集中、多日活动 | 按有记录的日期识别活动密集时段 |
| /graph | 保留 Event / Venue / District / Hotel；添加带距离的 NEAR 关系；删除查询与决策路径 | 查看活动到城市位置及酒店资源的连接 |
| /hotels | External Demand Signals；酒店组合与切换；日期/半径筛选；活动来源状态 | 搜索酒店附近活动，并与现有 RMS 和业务经验结合使用 |
| /insights | 同月份商圈活动量、类别、已配置场馆、活动场馆集中度、酒店资源比较 | 对照商圈活动构成和已配置资源，而非推算收入 |
| /evidence | 字段值、提取方式、来源 URL、核验和更新时间；冲突候选保持 Needs review | 追溯来源，并识别仍需人工核对的信息 |

继续使用统一浅蓝白色样式、导航、间距和卡片。未添加新的页面组件体系；修改既有 DemandIntelligence、RevenueOutlook、OpportunityAnalysis、TrustCenter、EventCard 和 Map 组件，移除 Graph/QueryPrototype。内部保留部分旧组件文件名，以减少架构变动。

## 数据处理

- 删除价格复核计划、AI 查询解析和自动冲突候选选择函数；移除图谱中的假设决策节点。
- 关注等级内部规则保持兼容；公开理由仅为语义因素，不渲染分数、加分和阈值。证据不足的真实记录保持 UNKNOWN。
- 重要活动时段按每天实际覆盖记录计算，再将原因相同的连续日期合并。多个活动、至少两个商务活动、持续三天以上活动分别产生对应理由；日期范围截断到当前月份。
- 商圈场馆集中度显示最集中的场馆及其活动数/已关联场馆活动总数；没有数据时明确为空。配置场馆、酒店数量是样本，DEMO 分组不表示真实行政边界。
- 场馆与酒店 NEAR 连线仅来自核验坐标，限制10 km内；不表示活动对酒店造成经济影响。未核验坐标不用于距离计算。
- 合成冲突日期仅用于独立演示；没有真实 URL，不标为 Verified，不写回任何活动。

## 文件变化

六个 `src/pages/*/index.tsx`、上述共享组件、`src/components/Layout/index.tsx`、`src/services/intelligence.ts`、`src/services/repository.ts`、`src/types/index.ts`、`src/data/trust-demo.json`、版本元数据与测试/说明。包内 `FILES_CHANGED.txt` 列出相对 V1.1 的精确文件变化。

原始 events/venues/hotels/districts/evidence/meta JSON 和 adapter.ts 未修改。新增 V1.2 UI 回归测试，替换已删除功能的 V1.1 测试。

## 限制

样例活动全部为 DEMO；酒店名录不完整，场馆规模和行业重要性无可信数据。没有实时采集、LLM调用、RMS连接、AI抽取、自动定价或需求预测。额外 API 凭据仅存于忽略的本地文件，不参与浏览器代码，也不随包分发。

真实 AMap 网络、鉴权、WebGL 及响应式视觉布局仍需浏览器验收。没有截图或线上部署；本次以逐页界面变化说明交付。代码仅在本地功能分支，未推送 GitHub。
