# 复核意见处理(2026-10-18)

复核人先读了 GitHub `55d8ca1`,又打开线上站点,报回五条。下面逐条记录**核实结果、修法、以及怎么验证**,包括没修到的地方。

| # | 问题 | 定性 | 状态 |
|---|---|---|---|
| 1 | 写接口缺少鉴权 | P1 | 已修(两层) |
| 2 | 审核可能错误延续(省略 value 后仍 Verified) | P1 | 已修 |
| 3 | 合并后证据与活动不一致(只改数据库列,不改 API 读的 payload) | P2 | 已修 |
| 4 | 撤销合并不恢复数据,却返回成功 | P2 | 已修 |
| 5 | 数据接口 7.1 MB、慢网约 11 秒超过 10 秒超时 | 风险 | 已缓解(ETag/304 + 超时),未改数据分片 |

---

## 1. 写接口鉴权(P1)

**核实**:复核人说的是对的,而且比"没鉴权"更具体:

- 线上 `POST /api/review` **匿名返回 401**——nginx 确实在用 basic auth 保护写方法(规则在 `/etc/nginx/conf.d/menduner-auth.conf`,不在仓库的 `deploy/nginx-menduner.conf` 里,所以从代码看像"被注释")。
- 但**后端本身不鉴权**:直接 `POST 127.0.0.1:8000/review` 匿名 → **200**。任何能接触后端端口的东西(本机进程、误配的代理、忘记 nginx 规则的新部署)都能写。复核人在本地测到的 200 正是这一层。

**修法(两层,缺一不可)**:

1. `backend/auth.py` 新增写接口依赖:请求必须携带 `X-Menduner-Login`(nginx 从 basic auth 的 `$remote_user` 填写,客户端自带的同名头会被覆盖),否则 **401**;脚本可用 `Authorization: Bearer $MENDUNER_WRITE_TOKEN`。
   - 应用到 `POST /review`、`POST /review/event`、`DELETE /review/{id}/{field}`、`POST /venues/merge`、`POST /venues/coordinates`。
   - **fail-closed**:没有任何身份 → 拒绝;不会"默认允许"。成功响应用 `authenticated_as` 回显身份。
2. `deploy/nginx-menduner.conf` 与线上对齐:写方法要口令、`proxy_set_header X-Menduner-Login $remote_user;`、两个 telemetry 端点豁免;新增 `deploy/nginx-menduner-auth.conf` 保存方法映射表。
3. 开发环境:Vite 代理在设了 `MENDUNER_WRITE_LOGIN` 时补这个头;`frontend/.env.local` 已加 `local-dev`,本地审核页照常可用,而直接 curl 后端仍是 401。

**线上验证**(部署后实测):

```
POST 127.0.0.1:8000/review                  -> 401   (后端直连,匿名)
POST /api/review                            -> 401   (经 nginx,匿名)
GET  /api/status                            -> 200   (读不受影响)
带临时账号 -u ... POST /api/review           -> 404 {"detail":"Event not found"}
      ↑ 证明 nginx 把登录名转发到了后端(否则是 401),且后端接受了身份
带临时账号 POST /api/venues/coordinates      -> 400 {"detail":"Unknown venue: does-not-exist"}
临时账号已删除,htpasswd 只剩原用户。
```

## 2. 审核错误延续(P1)

**核实**:`crawler/review.py` 的 `resolve()` 在 `reviewed_value IS NULL` 时**跳过绑定检查**,于是"省略 value 的审核"对之后任何值都成立。`POST /review` 的 `value` 是可选字段,直接把 `None` 存进 `reviewed_value`。

**修法**:

- **服务端绑定**:`POST /review` 不再信任客户端传来的 value,而是从**当前存储的 claim**(`evidence.payload.value`)读取真实值并绑定。客户端传了 value 但和当前 claim 不一致 → **409**(页面已过期,刷新后再审)。
- **解析层兜底**:`resolve()` 中 `reviewed_value IS NULL` 现在解释为"审核的是**该字段为空**这件事",只在这个字段仍然为空时生效——和 `AbsentConfirmed` 同一语义。任何后来出现的值都不会被这次审核覆盖。
- **历史数据**:同一逻辑让过去那些"无绑定"的 Verified 决定自动失效。线上库 137 条决定中 **9 条没有绑定值**,其中 **5 条是坏掉的 Verified**(organizer/endDate/districtId,10-13 记录),4 条是合法的 `AbsentConfirmed`。这 5 个字段会回到待审队列,需要再看一次——用 `scripts/report_unbound_review_decisions.py` 可以列出来。

**测试**:API 层(无 value 审核 → 记录的 `reviewed_value` 等于当前 claim;传过期 value → 409)、解析层(NULL 绑定只对空 claim 生效)、以及"匿名写入 401"。

## 3. 合并后证据与活动不一致(P2)

**核实**:`backend/venues.py` 合并时对 `evidence` 只执行 `UPDATE evidence SET value=?`,而 `snapshot()` 服务给前端的是 `evidence.payload`。所以活动行的 `venueId` 变成了存活场馆,API 读到的证据 claim 仍指向被删掉的场馆——知识图谱的场馆边因此断开。

**修法**:新增 `_rewrite_served_claim()`,同时写 `value` 列与 `payload.value`,合并时对每个迁移活动调用;测试断言 `snapshot()` 读出的 claim 值(而不只是列)等于存活场馆。

## 4. 撤销合并不恢复数据(P2)

**核实**:`revert` 分支只从别名文件删掉映射、写一条 `merge_reverted` 日志,然后返回 `{"reverted": True}`。被删除的场馆行、活动引用、证据都没恢复,而且 `undo` 信息根本没被记录。

**修法**:

- 合并时把恢复所需状态写进 `venue_edits.detail.undo`:`alias_payload`(被删的场馆行)、`carried`(从别名借给存活行的字段)、`events`(每个活动迁移前的 `crawler_evidence`/`evidence` claim 原值)、`observations`(被改写的原始记录 key)。
- 撤销时在一个事务里恢复:插回场馆行、把活动与两个证据表写回别名 id、恢复被借走的字段(仅当存活行仍是合并时借来的值,后来的修改优先)、删掉合并时生成的审核决定、最后才删别名映射。
- **没有 undo 记录的旧合并**:明确报错("没有留下可恢复的数据"),不再假装成功;已有场馆行存在时也拒绝,避免覆盖真实数据。
- 测试:合并→撤销→断言场馆行、事件引用、API 读到的证据值、审核决定全部回到合并前;旧合并撤销报错;覆盖保护。

## 5. 加载性能与超时(风险)

**核实**:数据接口 7.1 MB(本地 5.0 MB),gzip 后 1.2 MB;后端组装只要 0.06 s,超时是纯网络。`/api/dataset` 没有任何缓存协商,前端又用 `cache: "no-store"` + 10 秒超时,慢网必挂。

**修法**:

- `/api/dataset` 增加 **ETag**(body 的 sha256)+ `Cache-Control: no-cache`:浏览器第二次加载带 `If-None-Match`,命中返回 **304 空 body**。
- 前端超时 10 s → **45 s**,并且 `cache: "no-store"` → `"no-cache"`(允许条件请求);超时提示说明数据大小与重试。
- **数据分片没做**:87% 是 evidence 行,而 event 状态推导依赖它,拆分会牵动 `data.ts`/`intelligence.ts`/`knowledgeGraph.ts` 的核心逻辑,这次不动。如果第一次加载仍然偏慢,下一步应该是"核心数据 + 按需证据"两个接口。

**线上实测**:

```
第一次 GET /api/dataset : 200  7,112,628 bytes(原始) / 1,207,569 bytes(gzip)
第二次起(真实浏览器)     : 304  0 bytes        ← 服务器访问日志
```

nginx 访问日志里,headless Edge 首屏 `200 1207950`,后续每次都是 `304 0`;页面控制台 0 条错误。

---

## 部署与验证

- 后端:新增 `backend/auth.py`,改动 `backend/main.py`、`backend/database.py`、`backend/venues.py`、`crawler/review.py`。
- nginx:线上 `/api/` 增加 `X-Menduner-Login` 转发;仓库配置改为与线上一致,并补 `deploy/nginx-menduner-auth.conf`。
- 前端:超时/缓存/提示、`vite.config.ts` 开发登录头。
- 测试:**532 后端**(+7)、**128 前端**全绿。新增用例覆盖:匿名写拒绝、Bearer 令牌、无 value 绑定、过期值 409、合并 payload 一致、撤销恢复、旧合并拒绝、dataset ETag/304。
- 部署时没有改动任何人工数据;唯一可见变化是那 5 条无绑定审核决定失效、对应字段回到待审队列。
