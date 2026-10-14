本文件为历史说明。当前V1.5真实来源与必要迁移以[CRAWLER_V1.5_REPORT.md](CRAWLER_V1.5_REPORT.md)及[crawler/README.md](../crawler/README.md)为准；API字段仍兼容。

# V1.3 历史契约说明

接口字段仍兼容；V1.4采集、去重与按来源发布语义以[CRAWLER_V1.4.md](CRAWLER_V1.4.md)及[crawler/README.md](../crawler/README.md)为准。以下为V1.3记录。

# V1.3 API 与数据契约

## Event

SQLite `events` 表保留 `id/name/category/startDate/endDate/venue/district/source/verification_status`。`venue`、`district`、`source` 存储对应表的 ID；API 同时返回既有前端兼容的 `venueId/districtId`、`demo` 及 organizer/attendance/sponsor 等扩展字段。扩展原始内容保存在 payload JSON。

日期为 ISO YYYY-MM-DD 或 null。采集模型拒绝无效日期、反向日期范围、重复 ID；外键防止无效场馆/商圈关联。Mock 采集强制 `demo=true`，不能升级为真实活动。

## Evidence

SQLite `evidence` 包含 `event_id/field/value/source_url/verification_status`，加上唯一 `id`、`entity_id` 与兼容前端的 payload。API `value` 保留 JSON 原类型，缺失为 null。

- 活动证据的 event_id 对应活动；场馆/酒店参考证据 event_id=null，通过 entityId/entity_id 关联各自实体。
- `GET /evidence?event_id=...` 只返回活动字段；完整证据集合同时含参考实体。
- API 同时保留 `status/sourceUrl/sourceName/method/updatedAt/sourceRole`，现有 normalizeDataset 无需重建。
- Mock 来源 `source_url=null`、method=mock_adapter、显式合成说明；official_venue/government 仅表示适配器类型，不能作为核验依据。
- null 字段为 Missing；缺少来源 URL 的 Verified 值降为 Needs Review。合成冲突沿用原候选值并保留 Conflicting。
- 活动聚合状态优先级为 Conflicting → Needs Review → Unverified → Missing → Verified。前后端遵循相同规则。
- 场馆/酒店参考数据继承 V1.2 现有来源和核验标签，本次不声称重新核验网页。坐标证据不证明活动真实发生。

## 来源与时间

`sources` 保存适配器ID、名称、类型、mock标识、URL及成功采集时间。Source count 是已采集来源适配器数，不是已核验网站数；状态条另示 MOCK 数。

`runs` 记录每次成功批次、更新来源、记录数和 UTC 时间。status.lastUpdated 是最后成功写入时间，不是页面浏览时间或源网页发布时间。前端显示北京时间。空数据库 lastUpdated=null，revision=0。

## 更新与失败

采集器先读取、归一化和校验所有指定源，再使用一个 SQLite 写事务更新参考资源、来源及事件/证据。按来源替换本批记录：删除该来源不再提供的事件并级联删除对应证据；其它来源的数据不受影响。相同批次重跑不会重复增加事件，但生成新的成功运行版本。

采集失败不写入；写入中出现外键或主键冲突则整体回滚。不同来源撞ID会失败，原型不猜测跨来源实体匹配、不自动合并冲突。实际来源身份匹配、来源历史版本、差异审核和实时采集留待后续。

API 每个请求独立连接；`/dataset` 的 BEGIN 读事务使活动、参考资源、证据、状态来自同一数据库快照。接口只读，无上传或写操作。为小样本演示返回完整集合，未实现分页或大规模查询优化。

## 扩展适配器

`crawler/adapters/mock.py` 定义 SourceAdapter 协议及 CollectedSource。现有两个适配器读取不同形状的本地 JSON；不联网。CLI `--source all|official_venue|government` 可运行指定源，`--db PATH` 可隔离数据库。

真实来源接入须增加合法采集、字段 URL/原文/时间留存、身份匹配及人工核验流程；当前 ingest 明确只接受 mock 批次。没有 LLM、自动来源裁决或自动核验。

实现参考：FastAPI 的 [lifespan 测试说明](https://fastapi.tiangolo.com/advanced/testing-events/) 与 Python [sqlite3 事务/连接说明](https://docs.python.org/3/library/sqlite3.html)。连接在请求后显式关闭，采集事务失败时回滚。
