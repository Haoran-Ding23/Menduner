# Menduner Frontend V1.2

Traceable city event intelligence and external demand signals for hospitality decision makers.

在现有 V1.1 上增量更新。保留 React、TypeScript、Vite、Ant Design、React Router、AMap 2.0、ECharts、React Flow，以及六页路由、布局、数据适配器和本地 JSON。

## V1.2 活动情报

- 地图：活动关注因素、日期、场馆、商圈、邻近酒店资源与证据入口；酒店资源点和选中活动连线保留，移除需求层开关。
- 日历：重要活动时段，逐段解释重叠、商务活动集中或多日活动；支持日历高亮和未来30天关注清单。
- 图谱：活动、场馆、商圈与酒店关系；NEAR 连线来自核验坐标上的近似直线距离。移除查询原型、客群假设及决策节点。
- 酒店：酒店组合、日期、距离筛选、附近活动类别及来源状态；供酒店管理者结合现有 RMS 和业务经验使用。
- 商圈：活动量、类别、场馆集中度及酒店资源分布；均为当前配置样本统计。
- 证据：字段值、来源、核验状态、更新时间；冲突保留候选值并显示 Needs review。

**DEMO / Synthetic data / Not real event intelligence**。全部样例活动仍是合成数据。Attention 是活动关注等级，界面只解释因素，不显示内部评分或阈值。场馆重要性没有可信资料时明确标为未知。没有定价建议、收益预测、AI 决策输出或聊天机器人。

原 Evidence 的可选 `sourceRole`、`confidence`、`confidenceMethod` 字段继续兼容，适配器保持不变；移除合成置信度评分演示。完整改动见 `CHANGELOG_V1.2.md`，验证范围见 `VALIDATION.md`。

## 已有 V1.1 的增量升级

ZIP 包含完整 `frontend/` 源码和相对 V1.1 提交 `282f80f` 的 `update-from-v1.1.patch`。已有本地改动时，请先检查补丁，保留自己的修改。

```powershell
cd C:\Users\haora\Desktop\Menduner
git status --short
git switch -c feature/frontend-v1.2
git apply --check C:\Users\haora\Downloads\Menduner-frontend-v1.2\update-from-v1.1.patch
git apply C:\Users\haora\Downloads\Menduner-frontend-v1.2\update-from-v1.1.patch
```

补丁检查失败表示本地版本不同，需要合并差异。仅更新前端，保留已有仓库及后端。

## Windows 启动（PowerShell）

将 ZIP 中的 `frontend` 文件夹放入已有 `Menduner` 仓库。不要替换仓库或爬虫文件。

```powershell
cd C:\Users\haora\Desktop\Menduner
# 若分支已经存在，用 git switch feature/frontend-v1.2
git switch -c feature/frontend-v1.2
cd frontend
npm install
if (!(Test-Path .env.local)) { Copy-Item .env.example .env.local }
notepad .env.local
npm run dev
```

安装 Node.js 22.12+ 或 24 LTS。浏览器打开 `http://localhost:5173/map`。根据 Vite 终端显示的实际端口操作；不要把此地址作为公网部署地址。

```powershell
npm test
npm run build
```

默认不配置地图也能使用六页的列表、日历、图谱、统计与证据；地图区域会显示待配置状态。

## 高德安全配置

在 `.env.local` 填入自己控制台的三项配置：

```dotenv
VITE_AMAP_KEY=你的Web端JSAPI_Key
VITE_AMAP_SERVICE_HOST=/_AMapService
AMAP_SECURITY_CODE=你的安全密钥
```

**安全密钥变量不得带 `VITE_` 前缀**。Vite 的本地开发代理在服务端向固定高德上游附加 `jscode`，浏览器仅收到公开 JSAPI Key 与代理地址。配置文件被 Git 忽略，ZIP 不含任何真实凭据。代理固定匹配 `/_AMapService/v4/map/styles` → `webapi.amap.com`，其余 `/_AMapService` → `restapi.amap.com`。修改配置后重启服务。默认监听 `127.0.0.1`，不要改成公开监听后将此开发代理当成生产服务。

在高德控制台设置与本地测试地址相符的域名限制。确认 Web 端 JSAPI 权限、浏览器联网和 WebGL 可用。若超时/鉴权失败，检查这些配置，不会生成假地图替代。SDK 和瓦片需访问高德域名。

`npm run build` 只生成静态页面，**不包含这个开发代理**。将来部署时需要独立服务器/Nginx 安全代理，使用官方文档配置；本版本不部署、不创建 FastAPI、不启用收费服务。

官方依据：https://lbs.amap.com/api/javascript-api-v2/guide/abc/jscode

## 页面与交互

| 路由 | 已实现交互 |
|---|---|
| `/map` | 年/月/商圈/类别/DEMO 开关；列表与标记共享过滤；详情；同址活动选择；选中活动定位；空状态 |
| `/calendar` | 月/周视图；前后月份及周；每日活动数量；多日/跨月/跨年事件；拥挤日期展开；详情与地图跳转 |
| `/graph` | 选择活动；展开/收起商圈酒店；节点详情；边高亮；缩放、平移、MiniMap；活动/场馆跳转 |
| `/hotels` | 酒店、日期范围、距离筛选；核验坐标的近似直线距离；排序列表；来源；缺少坐标处理 |
| `/insights` | 数据计算的全年数量、商圈对比、月份趋势、类别和场馆分布；图表点击筛选；活动表及地图跳转 |
| `/evidence` | 活动搜索、状态过滤、字段证据、实体来源、提取方式、冲突/缺失/复核、原始 URL 和更新时间 |

右上角设置可以导入 JSON（最大 10 MB）并恢复样例。导入只影响当前浏览器会话，刷新恢复样例。六页通过 `event` URL 参数引用同一活动；Map 与 Calendar 共享 `year/month/district/category/demo`。

## 样例与真实性

- **10 条活动全部是合成 DEMO**，并非真实 Suzhou 活动新闻。覆盖多日、跨月、跨年、缺失、冲突、待复核等场景。
- 两个实际测试场馆及一家酒店的名称、地址、坐标来自下列高德 POI，查阅日期 2026-10-10。坐标明确使用 GCJ-02，顺序 `lng, lat`，不混用 WGS84/BD09。
- 商圈仅为明确标记的 DEMO 分组，不是核验行政归属或精确地理边界。不绘制假边界。
- 真实场馆坐标不代表 DEMO 活动真实发生。真实导入活动还必须有 `venueId` 字段的匹配核验证据，才能使用场馆坐标上图或计算酒店距离。
- 缺失值保持 `null`；没有地图点的事件仍显示于活动列表。样例活动来源显示“来源待核验”，不把场馆 POI 冒充活动事实来源。
- 酒店距离不是道路距离、需求预测、入住率或收入贡献。图谱没有 Event → Hotel 经济影响边。

来源：

- 苏州国际博览中心：https://ditu.amap.com/place/B02000IVJP
- 独墅湖影剧院：https://ditu.amap.com/place/B02000K20E
- 苏州洲际酒店：https://www.amap.com/place/B02000K05N

## 数据接口与导入

`src/data/` 中的五个 JSON 和 `meta.json` 经同一适配器加载。完整导入格式：

```json
{"events":[],"venues":[],"hotels":[],"districts":[],"evidence":[],"updatedAt":"2026-10-10T06:45:00Z"}
```

也接受活动对象数组。请勿导入个人数据或凭据。参考 `src/types/index.ts` 与样例文件。字段 ID 在各集合内必须唯一。其他页面不各自维护数据副本。

数据服务：`getEvents/getEventById/getVenues/getHotels/getDistricts/getEvidence/getGraphData`。当前采用同步 JSON；未来 FastAPI 适配应将调用改为异步加载并增加错误/加载状态，不应宣称已完成后端接入。

适配器保留每条活动的所有原始列于 `raw`，支持下列常见别名；日期必须为 `YYYY-MM-DD`，人数必须是非负数字。缺失 ID 采用导入行序号，跨文件更新请提供稳定 `event_id`。

| 前端字段 | 可识别列名 |
|---|---|
| `id` | `id`, `event_id`, `Event ID` |
| `name` | `name`, `event_name`, `Event Name`, `活动名称` |
| `category` | `category`, `event_type`, `Event Type`, `活动类型` |
| `startDate/endDate` | camelCase, `start_date/end_date`, `Start Date/End Date`, `开始日期/结束日期` |
| `venueId/districtId` | camelCase, `venue_id/district_id` |
| `organizer/attendance/sponsor` | camelCase、小写、`Organizer/Attendance/Sponsor`（部分中文别名） |

**仓库没有提供原始 21 字段规范或真实 crawler 输出**，因此不能验证精确兼容性。已保留原始列和常见字段映射；未来需对真实导出文件补充映射。场馆/商圈按 ID 显式关联，不根据名字猜测。

Evidence 的 `method` 保留传入值，包括 direct_web、official_venue_reference、verified_external_reference、unverified_internal_reference、derived、rule_based、manual。没有来源 URL 的 Verified 值标为 Needs Review。仅有导入值时生成 Unverified/Missing 记录，不自动核验。字段值与对应关系应由采集流程及人工复核保证。

## 验证与限制

详见 `VALIDATION.md` 和 `test-results.txt`。自动化 UI 测试使用 jsdom；地图 SDK 与 ECharts 在测试中替换为 mock，因此不能证明真实瓦片、WebGL、图表点击或实际浏览器布局已通过验收。生产构建经过 TypeScript 检查。

当前环境没有支持的本地浏览器自动化工具，未生成六页截图，也未声称真实高德地图已显示。完整浏览器验收请在 Windows 上启动后，按 `VALIDATION.md` 检查并截图。没有将工作推送 GitHub 或合并 main。
