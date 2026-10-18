# 客户账号与开通流程(2026-10-18)

真实可用的开通链路:**邀请码 → 注册(四周试用)→ 提交开通申请 → 对公转账 → 管理员确认 → 开通**。
服务端按账户上的日期判定套餐,前端只做展示;没有在线支付,也没有"点了就开通"的假状态。

## 1. 角色与两套认证

| | 客户(产品账号) | 运营/审核(内部) |
|---|---|---|
| 登录方式 | 登录名 + 密码,HttpOnly 会话 Cookie | nginx HTTP Basic(`/etc/nginx/.htpasswd`) |
| 权限判定 | `backend/accounts.py` 按试用/订阅日期推导套餐 | `backend/auth.py` 按 `roles.json` 判角色 |
| 入口 | `/register`、`/login`、`/plans` | `/review` 审核台(含「客户与开通」面板) |
| nginx | `/api/account*` **豁免 Basic**(自带会话) | `/api/admin/*`、`/api/review*` 等始终要求 Basic |

两条链路互不替代:客户账号不能进审核台;运营 Basic 账号也不带客户套餐。

## 2. 数据库

初始化时自动建表(`backend/accounts.py:dial`):

- `customer_accounts`:登录名(唯一、忽略大小写)、称呼、酒店、密码哈希、套餐、试用截止、订阅截止、邀请码、暂停位、创建/最后登录时间。
- `customer_sessions`:会话 token 的 **sha256**、账户、创建/过期时间(14 天)。Cookie 里只有随机 token。
- `invite_codes`:码、套餐、试用天数、可用次数/已用次数、备注、创建人、过期时间。
- `customer_orders`:账户、套餐、月数、金额(服务端算)、备注、状态(pending/confirmed/cancelled)、确认时间与确认人。

密码用 PBKDF2-HMAC-SHA256(20 万次迭代,随机盐),**不存明文**;登录失败按 IP+登录名限流(15 分钟窗口,8 次锁定)。

## 3. 客户流程

1. **邀请码**:运营在审核台「客户与开通」→ 选套餐(专业版/企业版)、试用天数(默认 28)、可用次数,生成 `MND-XXXX-XXXX`,复制发给客户(单次码用完即失效,码有 30 天有效期)。
2. **注册**:客户打开 `/register`,填邀请码、登录名(3–32 位字母数字 `._-`)、称呼、酒店(可选)、密码(≥8 位)。成功后**立即登录并开始试用**;邀请码使用次数 +1。
3. **试用**:账户状态 `trial`,套餐就是邀请码上的套餐(试用期专业版=1 家酒店,企业版=多店)。
4. **申请开通**:试用结束前,客户在 `/plans` 点「申请开通」,选套餐和月数(1–36)、填开票/联系备注,提交后生成 `pending` 订单。**提交申请不会开通任何东西**。
5. **线下对公**:我们联系客户提供收款账户并开票;金额按 专业版 ¥980/酒店/月、企业版 ¥780/酒店/月 × 月数 计算(以合同为准)。
6. **确认到账**:运营在审核台待确认列表点「确认收款开通」;系统把 `subscription_ends_at` 按购买月数延长(日历月,与已有订阅衔接),账户状态变为 `active`,订单变为 `confirmed`,并记录确认人。
7. **到期**:订阅到期后服务端自动回到 `free`(账户仍在),付费工作流重新上锁,客户可再次申请续费。

试用期不重叠计算:开通从"现在"或"当前订阅截止"(取较晚者)往后延月数。

## 4. API

客户(会话 Cookie,`/api/account*` 免 Basic):

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/account/register` | 邀请码注册并登录(Set-Cookie) |
| POST | `/api/account/login` | 登录(失败限流) |
| POST | `/api/account/logout` | 退出并删除会话 |
| GET | `/api/account` | 当前账户 + 服务端推导的套餐 + 自己的订单 |
| POST | `/api/account/orders` | 提交开通/续费申请(金额服务端算) |

运营(HTTP Basic,admin;`/api/admin*` 始终挑战):

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/admin/invites` | 生成邀请码 |
| GET | `/api/admin/invites` | 邀请码列表(含使用/过期状态) |
| GET | `/api/admin/accounts` | 客户列表(套餐/状态/有效期/待确认订单数) |
| GET | `/api/admin/orders?status=pending` | 订单列表 |
| POST | `/api/admin/orders/{id}/confirm` | 确认收款 → 开通/续期 |
| POST | `/api/admin/orders/{id}/cancel` | 取消申请 |

## 5. 运营操作(日常)

```bash
# 生成邀请码(管理员 Basic;menduner 是管理员账号)
curl -u menduner:'<口令>' -X POST -H 'Content-Type: application/json' \
  -d '{"plan":"pro","trial_days":28,"max_uses":1,"note":"洲际-王经理"}' \
  http://127.0.0.1/api/admin/invites

# 查看待确认收款
curl -u menduner:'<口令>' 'http://127.0.0.1/api/admin/orders?status=pending'

# 确认收款并开通(把 <order_id> 换成上一步返回的 id)
curl -u menduner:'<口令>' -X POST http://127.0.0.1/api/admin/orders/<order_id>/confirm
```

审核台页面同样提供这些操作:「客户与开通」面板(仅管理员可见)可生成/复制邀请码、查看客户与有效期、确认/取消订单。

## 6. 安全与已知限制

- **没有 HTTPS**:站点目前是 `http://47.116.133.230`,会话 Cookie 未加 `Secure`。上线真实客户前必须配 TLS(否则口令与 Cookie 明文过网)。
- 登录限流是**单进程内存**实现:重启清零,多实例部署需换 Redis 等共享限流。
- 没有邮箱/手机验证与找回密码:邀请制阶段由运营线下核对身份;忘记密码目前需要运营重置(待做)。
- Cookie `HttpOnly` + `SameSite=Lax`;没有独立 CSRF token,靠 SameSite 与同源 JSON 请求,真实对外前建议补 CSRF。
- 订单金额服务端计算,前端展示仅作参考;对公合同金额可另行约定(差异由运营在确认时掌握,当前系统不支持改价,只能取消重建)。
- 管理端接口的权限只到 admin(不细分财务/运营角色);建议财务确认收款与账号管理分开时再引入角色。

## 7. 自检

```bash
# 客户注册接口不需要 Basic(应返回业务错误 JSON,而不是 401 挑战)
curl -s -o /dev/null -w '%{http_code}\n' -X POST -H 'Content-Type: application/json' \
  -d '{"invite_code":"MND-0000-0000","login":"probe","password":"12345678","name":"探针"}' \
  http://127.0.0.1/api/account/register        # 400(邀请码不存在)

# 运营接口始终要求 Basic
curl -s -D - -o /dev/null http://127.0.0.1/api/admin/accounts | head -5   # 401 + WWW-Authenticate

# 公开数据不受影响
curl -o /dev/null -w '%{http_code}\n' http://127.0.0.1/api/dataset         # 200
```

测试:后端 `crawler/tests/test_accounts.py` 13 项(权限、邀请码、注册校验、会话、过期推导、限流、订单确认/取消、月份算术);
前端 `tests/plans.test.tsx` 8 项(匿名/试用/过期三种状态、门禁跳转、注册表单提交、专业版单店/企业版多店)。

## 8. 还没做(按需)

- 找回密码 / 改密码 / 账户资料编辑;邀请码作废按钮(当前只能靠次数用完与过期)。
- 邮件/短信通知(试用到期提醒、确认收款通知、发票)。
- 套餐/价格配置化(现在写在 `backend/accounts.py:PLAN_PRICES` 与 `frontend/src/services/plans.ts`,两处需同步)。
- 财务侧导出(订单对账 CSV)与发票编号记录。
- 服务端按 feature 校验付费接口:当前付费门槛在账户套餐上,公开数据集仍全量可读;如果未来有"只对付费客户开放"的数据(如私有经营数据),必须在对应接口上校验 `entitlements(account)`。
