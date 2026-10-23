# 生产发布记录：工作台 / 去重 / 图谱查询（2026-10-24）

发布目标：`https://entgroup14.com`（阿里云 `47.116.133.230`，systemd + nginx，非 Docker）。

## 1. 部署了什么

| 类别 | 文件 |
|---|---|
| 后端 | `backend/main.py`、`database.py`、`weekly_report.py`，新增 `dedupe.py`、`tracking.py`、`graph_query.py` |
| 脚本 | `scripts/migrate_dedupe.py`、`migrate_workbench.py`、`capture_snapshot.py`、`verify_sample_fields.py` |
| 前端 | 重新构建的 `frontend-dist`（31 个资源，先删旧 `assets` 再拷贝，避免残留包） |
| nginx | `snippets/menduner-app.conf` 增加 `location /api/workbench/`（会话鉴权，见第 4 节） |
| 定时任务 | `menduner` 用户 crontab 增加每日 08:05 快照 |

## 2. 数据库迁移（已执行）

```bash
cd /srv/menduner
sudo -u menduner env MENDUNER_DB_PATH=/srv/menduner/data/menduner.sqlite3 \
  ./venv/bin/python -X utf8 scripts/migrate_dedupe.py --apply     # 加 canonical_id 并回填
sudo -u menduner env MENDUNER_DB_PATH=/srv/menduner/data/menduner.sqlite3 \
  ./venv/bin/python -X utf8 scripts/migrate_workbench.py --apply  # 建快照/跟进两张表 + 首份快照
```

结果：436 条记录 → 20 条归并到 9 个规范活动 → **416 个独立身份**；快照 416 行；
`integrity_check = ok`，外键问题 0。两个脚本各自先备份到 `data/backups/`。

## 3. 回滚

```bash
# 方式一：恢复整库（发布前的两份备份都存在）
sudo cp /srv/menduner/data/backups/menduner-before-dedupe-*.sqlite3 /srv/menduner/data/menduner.sqlite3
sudo systemctl restart menduner-backend

# 方式二：只回退派生字段/新表，原始记录一条不丢
#   UPDATE events SET canonical_id = NULL;
#   DROP TABLE IF EXISTS event_snapshots; DROP TABLE IF EXISTS event_followups;

# nginx 回退
sudo cp /etc/nginx/snippets/menduner-app.conf.bak-v17 /etc/nginx/snippets/menduner-app.conf
sudo nginx -t && sudo systemctl reload nginx
```

## 4. 为什么 nginx 要单独给 `/api/workbench/` 放开 Basic auth

站点的通用规则是**按方法**区分的：`GET/HEAD/OPTIONS` 免费，其他方法要求 HTTP Basic。
工作台的跟进状态是酒店账号自己写的，客户没有运维凭据，所以这个前缀必须 `auth_basic off`，
改由会话 cookie 鉴权 —— 与 `/api/private/`、`/api/tenant/` 同一套边界。后端在没有会话时
返回 401，因此这不是放开的口子。

`/api/graph/*` 与 `/api/dedupe/*` 只有 GET，走通用规则即可，无需改动。

## 5. 每日快照

```
5 8 * * * cd /srv/menduner && MENDUNER_DB_PATH=/srv/menduner/data/menduner.sqlite3 \
  ./venv/bin/python -X utf8 scripts/capture_snapshot.py >> /srv/menduner/data/snapshot.log 2>&1
```

脚本幂等，同一天重复执行会覆盖为最新值。**第二份快照出现后**，工作台的「本周变化」才会
开始显示新增 / 改期 / 取消；在那之前界面明确显示「尚无可比较记录」。

## 6. 发布后验证（实际执行）

```
页面（域名，11 个）            / /workbench /map /agenda /find-hotels /hotels /insights /graph /evidence /private /login → 全部 200
/api/status                   → eventCount 436
/api/dedupe/summary           → 9 簇 / 20 归并 / 416 身份 / 4 候选
/api/workbench/changes        → comparable=false，reason「尚无可比较记录（只有一份快照）」
/api/graph/district/taicang   → 53 活动 / 8 场馆 / 4 酒店
POST /api/workbench/followups → 未登录 401；登录后 200，租户 hotel-4cd0ec8d4420，adopted=unknown
GET  /api/private/weekly.xlsx → 200，19088 字节，工作表：概览/经营数据明细/本周活动/本周变化/待办/说明
数据库                        → 416 身份 / 快照 416 行 / 外键 0 / integrity ok；测试记录已清理
systemd 定时器                → menduner-crawl.timer(08:01)、menduner-ai-crosscheck.timer(08:34) 未受影响
```

## 7. 已知遗留

- 工作台「本周变化」目前只有一份快照，需等次日 08:05 之后才有内容。
- 酒店活动情报页仍使用原有 `assessDemand` 展示，未切到 `frontend/src/services/ranking.ts`。
- 经济贡献情景只在商圈洞察页，未进入周报。
