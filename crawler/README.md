**Latest 2026-10-15:** the two venue sources whose calendars are rendered in the browser — 苏州国际博览中心 (`expo`) and 苏州文化艺术中心 (`arts`) — are no longer audit-only. Both are read through the public JSON endpoint their own published JavaScript calls, and both now publish real dated events. See [V1.6.4_JS_RENDERED_VENUES.md](../docs/V1.6.4_JS_RENDERED_VENUES.md). The V1.6 priority refinement is in [V1.6_PRIORITY_SOURCE_REVIEW.md](../docs/V1.6_PRIORITY_SOURCE_REVIEW.md); the descriptions below record the original V1.6/V1.5 baseline.

# Current: V1.6 CityEvent source network

See [CRAWLER_V1.6.md](../docs/CRAWLER_V1.6.md) for the current registry, Tier 1 command, strict failure handling and coverage definitions. [V1.6_SOURCE_COVERAGE_REPORT.md](../docs/V1.6_SOURCE_COVERAGE_REPORT.md) records the live checks. The V1.5 instructions below describe the retained baseline; the new `all` selection is defined in the V1.6 document.

# Crawler Pipeline V1.5 — Real sources

小规模真实公开网页 → 保存HTML/JSON原文 → 确定性提取 → 字段校验与证据 → SQLite → 既有FastAPI。

生产命令仅选择真实来源，不会用MOCK补齐失败。演示数据和旧适配器已移入 `crawler/demo/`。前端UI与FastAPI路由结构保持不变。

## 当前代表性来源

| 选择 | 实际来源 | 范围 |
|---|---|---|
| government | 苏州市人民政府公开活动报道 | 两篇已核实URL的文化活动报道；保留转载来源与发布信息，不将发布日当活动日 |
| venue | 苏州交响乐团官方演出栏目 | 页面自身调用的公开GET演出列表；无需登录、token或上传接口 |
| event_platform | 上海乐历的苏州文化艺术中心演出页 | 公开列表及同站演出详情JSON-LD，限定苏州活动 |
| expo | 苏州国际博览中心官方展会日程 | 页面自身的 Vue 脚本调用的公开 JSON 展会日程；静态 header 里的 token 是站点自己发布的公开常量，每次运行重新读取，不保存 |
| arts | 苏州文化艺术中心官网演出日程 | 官网是 Nuxt 空壳，改读它自己打包 JS 里公开的 `/sue/api/cinema/*` JSON；端点字符串每次运行从官网 JS 里重新发现，不写死 |

默认 `all` 运行全部已注册来源（含上面两个场馆），不再需要额外的开关。这是原型，不是完整苏州活动覆盖。

## 安装与运行

沿用标准Python3.14 venv。新增BeautifulSoup4解析依赖和httpx代理所需socksio；全部固定版本在backend/requirements.txt中，并同步到环境参考清单。

从仓库根目录运行（Windows PowerShell）：

```powershell
# 先安装新依赖，也可重跑setup.bat
.\backend\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt

# 默认：每个来源最多3个详情记录，写入当前SQLite
.\backend\.venv\Scripts\python.exe -m crawler.run

# 本次报告使用的有限采集范围：每个来源最多5条（V1.6 起上限为 40）
.\backend\.venv\Scripts\python.exe -m crawler.run --max-items 5

# 只要两个前端渲染的场馆来源（V1.6.4 起它们会真的出数据）
.\backend\.venv\Scripts\python.exe -m crawler.run --source arts --max-items 40
.\backend\.venv\Scripts\python.exe -m crawler.run --source expo --max-items 40

# 单来源或隔离数据库
.\backend\.venv\Scripts\python.exe -m crawler.run --source government
.\backend\.venv\Scripts\python.exe -m crawler.run --source venue --db backend\data\real-test.sqlite3
```

Linux/macOS使用backend/.venv/bin/python。--max-items只允许1–5；不翻页、不执行站点JS、不使用登录、验证码、代理池或token端点。默认DB依旧backend/data/menduner.sqlite3，亦支持MENDUNER_DB_PATH。

开始前请确认希望使用的DB路径。首次真实运行发现旧DEMO事件、来源或演示分组时，会先通过SQLite backup完整归档至同目录 `.demo-archive-时间-标识.sqlite3`，再移除活动数据库中的合成记录和未使用演示占位资源。真实事件和真实POI参考值不删除。若发现真实记录仍引用mock来源，回滚清理并要求人工检查，不强行改写来源。备份与数据库不提交。

运行后在前端点击“刷新 API 数据”。API事件demo=false，source.mock=0。原前端手动DEMO交互仍是独立会话功能，不用于生产采集或API失败回退。

## 溯源与字段质量

每条raw保留original_url、source_name、crawl_time及原始HTML/JSON。列表/背景页单独标Context，不冒充事件。提取前保存的原文不被后续更新覆盖。

场馆行的 `address` 只取来源地点串里的地址部分（`crawler/addresses.py`）：`苏州 吴中区 山丘livehouse-斜塘店 松涛街1088号斜塘老街36幢` → `松涛街1088号斜塘老街36幢`，查地图时再降到 `松涛街1088号`。事件上的 `location` 始终是来源原文，不会被改写成地址；来源没给门牌号就保持 `地址待核验`，不编造。存量行用 `scripts/normalize_venue_addresses.py` 归一（dry-run 默认）。

统一字段仍为event_id/event_name/category/start_date/end_date/venue/location/organizer/source_url；兼容venue_id和district_id。字段证据保留value/source/source_url/confidence，附加snippet、method和原始记录ID，供后续人工或AI阅读同一网页核对。

- 完整演出日期或JSON-LD值标Unverified。政府报道的月日与标题年份组合、类别规则、场馆引用ID标Needs Review。
- **confidence是提取启发式分数，未校准，不是事实正确概率；官网身份也不自动产生Verified。**
- 未提及organizer/endDate/街道地址时保持null。出版日期、开票日期、演员或网站运营者不替代活动日期/主办方。
- 日期候选冲突保留原始片段及候选，并待复核，不自动判定正确来源。
- 场馆仅由明确名称生成稳定引用；未做坐标、行政商圈或经济数据补全。coordinates=null，无核验证据不上地图。
- 明确取消/删除的详情拒绝发布，raw仍保留。数据随页面变化，本次结果是采集时快照，不是未来日程保证。

现有API状态拼写保持Verified/Unverified/Needs Review/Missing/Conflicting，语义对应已核验、未核验、待复核、缺失与冲突，避免破坏前端适配器。

## 请求和更新

只发公开GET，保留UA，约每主机1秒间隔。网络错误及408/429/部分5xx最多重试2次；遇较长Retry-After停止，供稍后人工重跑。尊重robots规则；robots明确拒绝则不抓正文。

robots最多5次同主机重定向；政府站的robots地址当前转到同站HTTP首页，未返回有效规则，此情况记录为“no usable robots rules returned”。事件正文依旧使用HTTPS。跨主机跳转拒绝；不绕过401/403、不关闭TLS验证。个别站点规则不可获取或改变时记录失败，不用缓存搜索摘要或MOCK当作抓取结果。

同源source_id+item_key保持更新身份。新来源仅按规范化名称、日期和场馆上下文保守去重；别名/不同标题不自动模糊合并。同一字段多个来源值冲突时维持原显示值并保留全部证据，显示值不代表事实裁决。单源失败保留旧观测，其他来源继续；未出现的旧记录不自动认定撤回。

## 检查原文和运行报告

```powershell
.\backend\.venv\Scripts\python.exe -m crawler.inspect
.\backend\.venv\Scripts\python.exe -m crawler.inspect --event 报告中的事件ID
.\backend\.venv\Scripts\python.exe -m crawler.inspect --raw-id 原始记录ID
```

报告区分pagesCollected（不含robots请求）、rawRecordsCollected（含Context和同一JSON响应中的独立记录）、eventsProcessed、duplicatesDetected、eventsStored、evidenceRecordsGenerated。evidence计数为当前事件字段证据表，不含独立POI证据。失败详情在job/attempt中保存。退出码0为Success；2为Partial/Failed，不应把Partial包装成全部来源成功。

## 离线演示与测试

仅显式命令可以运行合成数据，并且要求独立DB：

```powershell
.\backend\.venv\Scripts\python.exe -m crawler.demo.run --db backend\data\demo-test.sqlite3
.\backend\.venv\Scripts\python.exe -m pytest backend\tests crawler\tests -q
.\backend\.venv\Scripts\python.exe scripts\smoke_pipeline.py
```

demo命令拒绝默认生产DB。HTTP冒烟脚本使用隔离DEMO库验证服务链路；真实采集结果另见docs/CRAWLER_V1.5_REPORT.md，两者明确区分。

## 架构

sources/{government,venue,event_platform}负责独立采集；http.py负责限量请求；extractor/负责HTML、公开JSON及JSON-LD提取；validator/负责schema；pipeline/负责去重、更新、归档清理及SQLite；demo/只用于测试。

本次必要迁移仅放宽crawler_raw_items.mock的旧CHECK约束为0或1。旧raw ID、外键及证据表结构保留，未改变API路由。
