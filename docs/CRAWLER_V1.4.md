# Crawler Pipeline V1.4

基线：团队环境提交f9d53f7。仅采集管线、SQLite增量迁移、测试与说明变化，前端UI及既有API路由保持不变。

## 新增数据库表

| 表 | 内容 |
|---|---|
| crawler_jobs | 任务ID、开始/结束时间、Success/Partial/Failed、JSON报告 |
| crawler_attempts | 每任务每来源状态、错误、接受和拒绝数量 |
| crawler_raw_items | 每次原始URL、来源名称、采集时间、原文、MOCK、处理状态和错误 |
| crawler_observations | source_id+item_key到稳定event_id的当前链接、规范化值及最新raw引用 |
| crawler_unified_events | event_id对应的统一schema和保守匹配fingerprint |
| crawler_evidence | event_id/field_name/value/source/confidence及来源URL、原始记录ID、核验状态 |

仅CREATE TABLE/INDEX IF NOT EXISTS，不ALTER既有表、不清库；后端启动和CLI均应用迁移。字段证据同时镜像到既有evidence payload，活动同时更新既有events，保持当前API与前端JSON契约。原始记录保存历史，观测和证据表保存当前视图。

## 验证

最终原始日志：crawler-v14-test-results.txt、crawler-v14-smoke-results.txt。

- Python3.14.8，现有8项后端测试+新增12项管线测试，共20项通过。
- 验证独立源契约、原始溯源、13→11去重、重复采集、稳定ID更新、冲突保留、单源失败继续、无效条目保留、重复key拒绝、不同场次/缺日期不乱合并、V1.3数据库增量迁移、写失败回滚与raw留存、MOCK不覆盖非DEMO活动。
- 实际CLI→临时SQLite→FastAPI→Vite/api通过；全部既有资源接口及六路由HTML壳通过。
- 将实际SQLite/API快照通过未修改的前端normalizeDataset适配器验证：11事件、冲突日期、独立场馆核验证据均保留；inspect命令及模拟失败CLI退出码2通过。
- 前端源码不修改；真实浏览器画面、地图联网及Windows命令尚无新增实机验收。HTTP壳通过不等于视觉验收。
- 测试保留上游Starlette/httpx弃用提示；未更改依赖版本。

## 设计边界

来源名称和URL均明确MOCK，URL采用保留.invalid域名。固定confidence是合成结构化提取分数、未校准、与核验状态独立。源角色不能代替已核验证据。

每个来源独立发布；不是三个来源的全局事务。失败来源保留上次已发布观测；缺失本批记录不自动删除。此版本只为小样本、可追溯和可验证的数据流演示，不是生产爬虫或实时城市情报。
