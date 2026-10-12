# Menduner Frontend V1.1 — Revenue Manager decision support

在现有 V1.0 checkout 上开发，分支 `feature/frontend-v1.1`。不重建仓库、不更改后端。React、Vite、Ant Design、React Router、AMap、ECharts、React Flow、六页导航和现有 JSON service 接口保留。

## 主要界面变化与商业价值（替代浏览器截图说明）

| 页面 | 新增界面与交互 | 收入经理得到的帮助 |
|---|---|---|
| `/hotels` | 顶部 My Hotels 多选组合与单酒店切换；原地图/列表保留；下方 Decision Support 卡片按规则优先级排序，显示7–14天复核窗口、已过窗口/进行中状态、建议、理由与证据按钮；RMS 对比说明卡 | 从“附近有什么”进入“先复核哪些、何时复核、为什么关注” |
| `/map` | 原空间分布卡增加 Hotel Demand Layer 开关；显示核验酒店点；已选活动与10km内酒店的虚线连线；卡片/详情展示 HIGH/MEDIUM/LOW/UNKNOWN、配置酒店数和最近距离 | 识别空间关联，跳转对应酒店，保持场馆坐标与活动关系证据的边界 |
| `/calendar` | 日历上方两个浅色 Outlook 卡片：规则关注日期及未来30天 HIGH 清单；点击日期段高亮格子；活动格子附优先级星标、HIGH 活动前30天准备提示，详情含复核建议 | 提前准备与持续关注；将月度排期转为人工复核清单 |
| `/insights` | 原 ECharts 统计保留；增加商圈机会分卡片、同月份比较表、行业计数按钮及客群假设说明 | 用同一批样本比较关注方向，避免凭漂亮数字判断市场机会 |
| `/graph` | 新增 DemandSignal、HotelDecision 节点和 MAY_SIGNAL / INFORMS_REVIEW 虚线；三列布局；决策路径开关；节点详情含来源和邻近酒店数；下方中英文 AI Query Prototype | 检查从活动类别到客群假设再到人工行动的解释链，查询结果可回到图谱与证据 |
| `/evidence` | 增加可点击四阶段流程说明；独立 DEMO Confidence/Conflict 卡片；原字段表增加 Confidence 列，缺少分数时不赋值 | 分清提取分数、来源可信性、字段核验和业务假设，检查模型为什么选择或暂不选择 |

新增界面沿用原 panel、字体、白/浅蓝背景、圆角、间距及响应式断点。未生成浏览器截图；本文件解释六页变化。仍需在真实浏览器检查 WebGL、地图瓦片、canvas 图表和1440/1280宽度视觉布局。

## 新组件和服务

| 路径（相对于 frontend） | 职责 |
|---|---|
| `src/components/DemandIntelligence/index.tsx` | ImpactTag、DemandExplanation、DecisionSupportPanel |
| `src/components/EvidenceSummary/index.tsx` | 官网/场馆/政府核验入口、独立来源数量及更新时间 |
| `src/components/RevenueOutlook/index.tsx` | 月度重点时段、未来30天清单 |
| `src/components/OpportunityAnalysis/index.tsx` | 商圈机会评分、比较表、行业/客群假设 |
| `src/components/Graph/QueryPrototype.tsx` | 不调用LLM的业务查询、结果解释与跳转 |
| `src/components/TrustCenter/index.tsx` | 管线说明、合成置信度、冲突选择演示 |
| `src/services/intelligence.ts` | 共享评级、邻近酒店、复核计划、日期窗口、机会评分、行业映射、查询及合成冲突复核 |
| `src/data/trust-demo.json` | 与事实字段独立的合成信任演示场景 |

主要修改：全部六页；共享 Map / EventCard / EventDetail；Layout 版本号；usePlatform 的带酒店参数跨页导航；types 中的向后兼容可选字段；adapter 的可选元数据读取；repository 的业务路径及来源值匹配；utils 中场馆冲突时不上图；global.css 新卡片样式；package 版本号和测试。原六个业务 JSON 内容/结构保持不变。可读性格式化限于本次修改的前端代码，不替换项目架构。

## 可解释规则

**Demand Impact = 复核优先级，非需求预测。** 类别分：商业45、文化/教育30、体育25、民俗20、政府15、其他10；多日加15；10km内存在核验坐标的配置酒店加15。总分最多75：HIGH≥70、MEDIUM≥40、LOW<40。每个详情列出分数来源。结束日期未知不假定持续天数或已结束。日期/地点不足则 UNKNOWN；真实记录还必须有日期、类别及场馆关系的一致核验证据。场馆冲突会停止空间推断。

酒店数仅来自当前配置目录，距离为近似直线距离。酒店组合只筛选当前酒店视图；事件级分级仍依据配置目录，并非个人组合的收益分级。

**机会评分 = 样本比较规则，非经济贡献。** `min(活动数,10)×4 + 商业占比×40 + min(核验坐标配置酒店数,3)/3×20`，四舍五入为0–100。HIGH≥60、MEDIUM≥30，其余LOW，无活动为UNKNOWN。缺少面积与完整酒店名录，所以不显示“真实酒店密度 High”。样例金鸡湖10月为2活动、1商业活动、1配置酒店，得35分/MEDIUM；不是硬编码。

日历重点段按 HIGH 活动覆盖日期合并并裁切到所选月份。未来30天使用 Asia/Shanghai 的今天至今天+29日，包含进行中活动；不受所选月份限制，受商圈/类别/DEMO筛选影响。

**AI Query** 为确定性原型：解析金鸡湖/独墅湖、中英文月份及年份，计算当前数据中 HIGH 活动与邻近配置酒店的交集。可返回0，不固定“3个”，不回答任意收益问题。

**Conflict DEMO**：合成主办方官网候选优先于政府/场馆/其他；同等级不同日期或真实候选不自动裁决。演示不写回数据，不把95%合成分数当事实概率，不把未核验值升级Verified。

## 保留的可信度边界

所有现有10条活动仍是合成DEMO。两个测试场馆和一个酒店保留已有核验POI坐标；商圈归属仍是DEMO分组。活动官网/政府来源没有核验资料时明确待核验，不能因为场馆POI存在就打活动官网✓。事件与酒店的经济影响没有被证明，客群节点为假设。无真实LLM、RMS接口、价格调整、FastAPI、Neo4j、在线部署或付费服务开通。
