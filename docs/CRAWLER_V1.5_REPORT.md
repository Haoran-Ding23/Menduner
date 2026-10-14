# Crawler Pipeline V1.5 — Real collection report

基线f34537b。有限真实请求、确定性提取和既有证据体系；未接入LLM，提取结果保留片段，可供后续AI/人工核对。

## 本次实际联网运行

命令：`python -m crawler.run --max-items 5 --include-expo`，默认现有SQLite。采集完成于2026-10-12 19:15:29北京时间。完整元数据见crawler-v15-real-report.json。网页后续变化可能改变结果。

| 指标 | 本次结果 |
|---|---:|
| 正文/公开数据页成功获取（不含robots） | 10 |
| robots请求（包含同主机重定向） | 5 |
| 原始记录保存 | 15 |
| 其中背景/列表Context记录 | 3 |
| 接受的事件来源记录 | 12 |
| 跨来源重复识别 | 1 |
| 最终事件 | 11 |
| 当前事件字段证据 | 120 |
| 自动标为Verified的事件 | 0 |
| 活动库中MOCK来源/DEMO事件 | 0 / 0 |

同一个JSON响应可保存多个独立事件raw，因此raw数量大于页数。证据数不包含独立POI参考证据。实际HTTP没有触发请求重试；重试行为已通过离线HTTP测试验证。

## 各来源

| 来源 | 成功页 | 事件来源记录 | 结果 |
|---|---:|---:|---|
| 苏州市人民政府公开文化活动报道 | 2 | 2 | Success |
| 苏州交响乐团官方公开演出数据 | 1 | 5 | Success |
| 上海乐历苏州场馆列表及详情 | 6 | 5 | Success |
| 苏州国际博览中心静态日程审计 | 1 | 0 | Partial：动态token日程未访问，不制造事件 |

整次包含博览中心审计的运行如实标为Partial，退出码2。三个默认核心来源均成功。

真实来源示例：

- [苏州市人民政府：2026第五届苏州金鸡湖中法文化艺术周](https://www.suzhou.gov.cn/szsrmzf/szyw/202610/0ba8650590584318b6c3051171a8c539.shtml)
- [苏州市人民政府：2026上海国际光影节金鸡湖分会场](https://www.suzhou.gov.cn/szsrmzf/wtly/202609/b211ae650d744fb69943e5fb88524f48.shtml)
- [苏交官方演出栏目](https://www.szsorch.com/shows-ticketing.html)；采集其自身使用的公开GET数据，未访问上传/登录/STS接口。
- [上海乐历苏州文化艺术中心列表](https://shanghaiconcerts.com/venues/suzhou-culture-arts-centre)，仅访问同站公开详情。
- [博览中心官方日程](https://www.suzhouexpo.com/zhanhuiricheng-389.html)，保存原文供复核。

## 数据质量

来源身份与字段核验分开。完整日期/JSON-LD为Unverified；政府报道中组合月日与标题年份、类别规则、名称引用ID为Needs Review。缺少活动结束日期/主办方时保持null，不采用发布日、开票日、演员或网站运营者替代。

Confidence是字段提取启发式分数，不是已校准概率。没有因为网站“官方”就把字段批量升为Verified。名称/场馆文字差异可造成保守冲突；不自动模糊合并。同一场次的跨来源记录保留各自raw及证据。

本次检查发现官方页面附带的getEventList.js会随机生成示例日历，明确排除；实际演出值来自公开GET记录。博览中心静态HTML只含动态占位，未将其当真实排期。政府robots地址转到同主机HTTP首页且未提供有效规则，已记录；活动正文始终HTTPS。平台robots允许公开演出页面，禁止API/private路径，未访问这些路径。

旧MOCK事件、来源、未使用演示占位资源和DEMO商圈分组先完整SQLite备份，再从活动库移除。真实POI数据保留；新场馆不猜测坐标或商圈，未核验位置仍不上图。

## 必要数据库迁移

V1.4的crawler_raw_items有CHECK(mock=1)，无法保存真实raw。仅将该约束迁移为CHECK(mock IN(0,1))，保持列、旧raw ID、外键及其它表结构。SQLite需要复制表以改CHECK；迁移事务和外键完整性有测试覆盖。API路由和证据结构未更改，片段/candidates等保存在现有payload JSON。

## 测试与验证

- Python3.14.8，36项后端/管线测试通过：原兼容测试、真实提取、HTTP重试、robots拒绝、跨主机拒绝、长Retry-After停止、发布日不冒充活动日、缺失保持null、内部日期矛盾待复核、真实去重更新、DEMO归档隔离、旧约束迁移、失败保留原观测、清理演示占位且保留真实POI。
- 实际真实SQLite → FastAPI /docs → Vite /api/dataset通过：11真实来源事件、MOCK sourceCount=0；原前端适配器读取真实快照通过。
- 离线服务冒烟采用隔离DEMO库，明确不冒充上述真实联网结果。
- Windows双击/浏览器视觉/真实高德地图无新增实机验收。前端UI未修改；没有自动坐标补全。
- pip check通过。上游Starlette/httpx弃用提示仍存在，没有为此改变API结构。

限制：仅少量固定政府文章及当前音乐季、平台列表；不是苏州活动全集。没有HTTP浏览器自动化、账号登录、token抓取、持续调度、模糊实体消歧、人工核验界面或收益预测。完整原文保存在本地SQLite，交付包不分发数据库或整篇网页。
