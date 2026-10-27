# 审核台登录与权限（为什么之前 ✓ 按钮点不了）

## 一、根因

| 环节 | 之前 | 结果 |
|---|---|---|
| `GET /api/auth/me` | nginx 强制 HTTP Basic | 浏览器从未被 challenge → 前端永远以为匿名 |
| 前端 | `canReview(identity)` 为 false | **✓ / ✗ 按钮全部禁用** |
| `POST /api/review` | 需要 Basic + `roles.json` 里的 reviewer | 客户账号（会话 Cookie）根本走不通 |

## 二、现在的做法（会话认证，角色仍由服务端决定）

1. `GET /api/auth/me` 不再要求 Basic；后端 `auth.principal` 增加**会话 Cookie 兜底**。
2. 角色仍来自 `backend/roles.json`（服务端文件，前端无法伪造）：
   ```json
   "users": {
     "menduner": { "role": "admin" },
     "liuge":    { "role": "reviewer" },
     "manager01": { "role": "reviewer", "name": "门店经理(演示)" }
   }
   ```
3. nginx 新增 `location ~ ^/api/review(/.*)?$ { auth_basic off; ... }`，把审核写操作交给应用层会话鉴权。
   **没有角色条目的账号 = 403**，权限边界不变。

## 三、怎么用（演示账号）

```
地址：https://entgroup14.com/login
账号：manager01
口令：Menduner#2026
```

登录后：
- 页面右上角显示为已登录；`/api/auth/me` 返回 `role: reviewer`
- 「数据质量与来源」页顶部**快速核对（3 项）**的 ✓ / ✗ 变为可点
- 点 ✓ → `POST /api/review` 记录 `decision=Verified`，带上当前屏幕上的值（后端 409 保护保留）

> 演示前请把口令改掉；这个账号是演示用，正式环境应给真实审核员单独开号并加入 `roles.json`。

## 四、端到端验证（服务器上实测）

```
POST /api/account/login  → {"authenticated":true,...}
GET  /api/auth/me        → {"authenticated":true,"login":"manager01","role":"reviewer"}
POST /api/review         → 200
  {"id":"rev:7242d16ff728138cd07f28a7f505c1f6","event_id":"evt-ded705d3a98fc9a4bf1043ae",
   "field":"sourceUrl","decision":"Verified",
   "reviewed_value":"https://www.suzhou.gov.cn/...","reviewer":"manager01"}
```

注意：这条测试写入了一条真实审核记录（sourceUrl = Verified）。若不希望在演示数据里留下这条，
可在审核记录里删除或忽略——它是一条真实的人工决定，记录本身是合法的。

## 五、安全备注

- 口令只在这里记录，`roles.json` 不含口令；
- 角色判定在后端完成，隐藏按钮不等于权限；
- 会话 Cookie 名 `menduner_session`；写操作没有会话或角色时返回 401/403。
