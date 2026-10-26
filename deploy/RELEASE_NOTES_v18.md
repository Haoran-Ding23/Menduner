# 生产发布记录：v18（2026-10-26，北京时间）

发布目标：`https://entgroup14.com`（阿里云 `47.116.133.230`，systemd + nginx，非 Docker）。
用户在本轮以 Release Owner 身份明确授权发布；GPT 在 Round 3 的"禁止部署"条款由该授权覆盖。

## 1. 本次上线内容

| 类别 | 内容 |
|---|---|
| 后端新增 | `backend/city_report.py`（按城市导出公开活动周报，390 行）、`backend/geo.py`（地理层级） |
| 后端修改 | `backend/main.py`（新增 `/reports/city/{id}.xlsx`、`/geo/tree`、`/geo/coverage`，加 `urllib.parse` import）、`backend/tracking.py`（`changes()` 支持 `until`，修正比较终点） |
| 前端 | 重新构建 31 个资源：口径模块与口径条、身份层去重（含 adapter 修复）、移动端导航、范围说明、F10 公开页隐藏内部编号与审核入口 |
| 数据 | 用高德逆地理给生产商圈补父级与行政编码：**20/20 匹配成功**，未解决父级 28 → 8（剩余为无坐标的街道） |
| 定时任务 | 沿用 10-24 部署的每日 08:05 快照（`menduner` 用户 cron） |

## 2. 数据库

- **无 schema 变更、无迁移**。`canonical_id`、`event_snapshots`、`event_followups` 均在 10-24 已存在。
- 本次只写 `districts.payload`（新增 `parentId`/`adminCode`/`township`/`businessAreas`/`matchLevel`，只补空不覆盖）。
- 备份：
  - `data/backups/menduner-before-v18-20261026-062537.sqlite3`
  - `data/backups/menduner-before-geo-backfill-20261026-062722.sqlite3`
  - `data/backups/geo-parent-mapping-20261026-062722.json`（逐条映射）

## 3. nginx

无需改动：新增路由均为 GET，走通用规则（GET 免 Basic），鉴权由应用层会话完成。

## 4. 发布后验证（实际执行）

```
systemctl is-active menduner-backend            → active
/status                                          → 200
/geo/tree, /geo/coverage                         → 200
/dedupe/summary                                  → 200
GET /reports/city/taicang.xlsx（未登录）          → 401
登录 manager01 后同一地址（2026-10-01~10-31）      → 200，10039 字节，头部 PK
  Excel 工作表：城市概览 / 活动明细 / 本期变化 / 来源证据 / 待确认事项
  活动明细：9 行 × 10 列（已移除内部 canonical_id 列）
  本期变化：比较区间 2026-10-24 → 2026-10-26（真实快照区间，非自然周）
前端资源数                                        → 31
```

## 5. GPT Round 3 三项必修的落实情况

| 项 | 结果 |
|---|---|
| 变化差分终点必须受查询区间约束 | ✅ `tracking.changes(until=)`，并有正向测试（历史区间不得混入截止日之后的变化） |
| 「消失」不得直接判为「取消」 | ✅ 文案改为「消失…可能是取消，也可能是采集未覆盖，需人工确认」 |
| 内部主键不得进 Excel | ✅ 删除「规范化身份」列；对外状态走映射；批次说明不再暴露内部列名 |
| 鉴权 ≠ 授权 | 🟡 策略已写入文档：公开城市活动对已登录账号开放；私有经营数据仍在 `/api/private/`、`/api/tenant/` 的租户鉴权下 |

## 6. 回滚

```bash
sudo cp /srv/menduner/data/backups/menduner-before-v18-*.sqlite3 /srv/menduner/data/menduner.sqlite3
# 或只回退地理补全
sudo cp /srv/menduner/data/backups/menduner-before-geo-backfill-*.sqlite3 /srv/menduner/data/menduner.sqlite3
sudo systemctl restart menduner-backend
# 前端回滚：重新部署上一版 frontend-dist（先删 assets 再拷贝）
```

## 7. 尚未上线/未完成

- 城市周报**只有 API**，前端页面未接入；PDF 版本未做。
- 审核文档的 F06（图谱样例与机场分型）、F08（桌面首屏密度）、F11（周报比较区间细化）、F12（数据批次展示）未做。
- §2 自动核验流水线未开始。
- `crawler/tests/test_douban.py` 的 4 个既有失败仍在（与近期改动无关，已用 stash 验证）。
