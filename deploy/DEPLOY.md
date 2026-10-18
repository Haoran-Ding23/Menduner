# 部署手册（阿里云轻量应用服务器 / Ubuntu）

面向：**1 台 2核2G 轻量应用服务器 + Ubuntu 22.04/24.04**，用 IP 直接访问，不买域名、不备案。

全流程约 30 分钟。每一步都可复制粘贴。

---

## 0. 下单时注意

| 项目 | 选择 | 原因 |
|---|---|---|
| 规格 | **2核2G** | 1G 在服务器上跑 `npm run build` 会 OOM |
| 地域 | 华东（上海） | 离苏州近，高德调用快 |
| 镜像 | **Ubuntu 22.04 / 24.04 纯净镜像** | 不要选「宝塔面板」：白占内存，还多一层攻击面 |
| 磁盘 | 40G | 系统+依赖约 3G，数据库 105MB，余量充足 |

买完后在**轻量服务器控制台 → 防火墙**里放行：

- **22**（SSH，通常默认已开）
- **80**（HTTP）← 必须手动加，否则浏览器打不开

> 「防火墙」在这里就是云厂商的安全组，不放行 80 端口，页面永远转圈。

---

## 1. 登录服务器

在控制台重置 root 密码，然后用本机终端：

```bash
ssh admin@47.116.133.230
```

首次会问 `yes/no`，输入 `yes`。

---

## 2. 装依赖（Ubuntu）

```bash
apt update && apt upgrade -y
apt install -y python3 python3-venv python3-pip nginx rsync
```

验证版本：

```bash
python3 --version    # 需 3.10+，Ubuntu 22.04 自带 3.10，24.04 自带 3.12
```

> 项目开发用的是 Python 3.14，但代码没有用到 3.14 独有语法，3.10 以上都能跑。

---

## 3. 建目录和运行账号

```bash
useradd -r -s /usr/sbin/nologin -d /srv/menduner menduner || true
mkdir -p /srv/menduner/data
```

---

## 4. 上传代码

发布包已经准备好了，在 **`C:\Users\haora\Desktop\menduner-upload`**，共 106 MB（其中数据库 105 MB）。
它只包含该上传的东西：源码 + 前端构建产物 + 数据库，**不含** Windows 虚拟环境和缓存。

**在你的 Windows 本机**新开一个 PowerShell 窗口，执行：

```powershell
cd C:\Users\haora\Desktop
scp -r menduner-upload admin@47.116.133.230:/srv/
```

然后把它改名成标准路径（在**服务器**上执行）：

```bash
mv /srv/menduner-upload /srv/menduner
ls /srv/menduner            # 应看到 backend  crawler  data  deploy
```

首次 `scp` 会问 `Are you sure you want to continue connecting?`，输入 `yes`，然后输入你设置的 root 密码。

> 105 MB 上传需要几分钟，取决于你的上行带宽。**中途别 Ctrl+C**，否则数据库会传一半。

---

## 5. 装 Python 依赖

回到**服务器**：

```bash
cd /srv/menduner
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r backend/requirements.txt
```

验证能导入：

```bash
./venv/bin/python -c "import fastapi, uvicorn, sqlite3, bs4, yaml; print('依赖 OK')"
```

> `requirements.txt` 里的版本是按 Python 3.14 钉住的。如果某个包在 3.10 上装不上，去掉那一行的 `==版本号` 重装即可，功能不受影响。

---

## 6. 迁移数据库里的旧路径（重要）

数据库里存了开发时的文件路径吗？没有——但 `runs`、`crawler_raw_items` 里存的是**网站 URL**，不受影响。这一节只需确认数据库可读：

```bash
./venv/bin/python -c "
import sqlite3
con = sqlite3.connect('/srv/menduner/data/menduner.sqlite3')
print('events:', con.execute('SELECT COUNT(*) FROM events').fetchone()[0])
print('hotels:', con.execute('SELECT COUNT(*) FROM hotels').fetchone()[0])
"
```

看到 `events: 145` 就说明数据库完好。

设置权限（只让服务账号能写）：

```bash
chown -R menduner:menduner /srv/menduner
chmod 750 /srv/menduner/data
```

---

## 7. 配置后端服务

```bash
cp /srv/menduner/deploy/menduner-backend.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now menduner-backend
```

检查状态：

```bash
systemctl status menduner-backend --no-pager
curl -s http://127.0.0.1:8000/status | head -c 200
```

`curl` 能返回 JSON 就说明后端起来了。如果失败：

```bash
journalctl -u menduner-backend -n 40 --no-pager
```

**注意**：后端只监听 `127.0.0.1:8000`，外部访问不到——这是故意的。这个 API **没有任何鉴权**，绝不能直接暴露。

---

## 8. 配置 Nginx

编辑配置文件，把 `__SERVER_NAME__` 换成你的公网 IP：

```bash
sed "s/__SERVER_NAME__/你的公网IP/" /srv/menduner/deploy/nginx-menduner.conf > /etc/nginx/sites-available/menduner
ln -sf /etc/nginx/sites-available/menduner /etc/nginx/sites-enabled/menduner
rm -f /etc/nginx/sites-enabled/default      # 去掉 nginx 自带的欢迎页，否则会抢占
nginx -t                                     # 必须显示 syntax is ok
systemctl reload nginx
```

---

## 9. 访问

浏览器打开：

```
http://你的公网IP
```

应该看到地图页面，右上角显示「城市活动情报 · 145 条」。

**如果打开是 nginx 欢迎页**：`sites-enabled/default` 没删干净。
**如果页面出来但列表空、右上角显示「API 不可用」**：后端没起来，看 `journalctl -u menduner-backend`。

---

## 10. 高德地图（最容易踩的坑）

页面出来了，但**地图区域可能是空白或只有灰底**。原因是高德的 Key 绑定了域名白名单，现在换成了你的服务器 IP。

到 [高德开放平台控制台](https://console.amap.com/dev/key/app) 找到你的应用：

1. **Web端(JS API) Key**（`VITE_AMAP_KEY`，即 `de269b65...`）→ 设置 → 把 `你的公网IP` 加进白名单
   - 如果高德不接受纯 IP，就填服务器 IP 也能生效；实在不行临时清空白名单（仅演示用，有被盗用风险）
2. 改完**要重新构建前端**（Key 是构建时打进包里的）：
   ```powershell
   cd frontend; npm run build
   scp -r dist admin@47.116.133.230:/srv/menduner/
   ```
3. 浏览器强刷 `Ctrl+F5`

**关于安全密钥（`AMAP_SECURITY_CODE`）**：开发时 Vite 会给高德请求注入 `jscode` 签名，生产环境没这一步。所以：

- 地图本体、标记、半径圈都正常显示
- **自定义地图样式失效**（底图用高德默认样式）
- **生产包里不会再用 `/_AMapService`**：`.env.local` 里的 `VITE_AMAP_SERVICE_HOST=/_AMapService` 是给开发服务器用的相对路径，打进生产包后它指向一个 nginx 上不存在的代理，而 nginx 的 SPA 回退会把这个路径回答成 `index.html` —— 高德 SDK 拿 HTML 当 JSON/JSONP 执行，每个带地图的页面都会报
  `SyntaxError: Unexpected token '<'`（这就是之前前端错误页里 98 条错误的唯一来源）。
  `frontend/src/components/Map/index.tsx` 现在只在**开发环境**接受相对路径，生产环境只接受**另一个域的绝对代理地址**，否则就让 SDK 直接请求高德。
- 如果以后真部署了签名代理，把它配成绝对地址（`https://你的代理域名/_AMapService`）并改 `deploy/nginx-menduner.conf` 里的 `^~ /_AMapService/` 块。**没有代理时**该块会按高德期望的格式回答（JSONP 返回合法 JS、普通请求返回高德错误信封），绝不返回 HTML。

已确认：前端包里**只有 JS Key**（本来就该公开），安全密钥没有被打进包，是正确的。

要恢复样式需要额外跑一个小代理进程，见 `deploy/nginx-menduner.conf` 底部的注释。

---

## 11. 写接口鉴权(必须做)

**读接口公开,写接口必须登录。** 任何知道网址的人都能读数据集是这个演示的前提;但如果写接口也开放,任何人都能批准/驳回证据、合并场馆、改坐标——对"证明数据可信"的系统是逻辑矛盾,而且一次匿名写入无法从来源页重建。这一层现在是**两层**:

**第一层:nginx 只对写方法要口令。** 方法映射单独放在 `/etc/nginx/conf.d/menduner-auth.conf`(仓库里是 `deploy/nginx-menduner-auth.conf`):

```nginx
map $request_method $menduner_deny {
    default "Menduner";   # POST / PUT / PATCH / DELETE 要口令
    GET off; HEAD off; OPTIONS off;   # 读不需要
}
```

```bash
apt install -y apache2-utils
htpasswd -c /etc/nginx/.htpasswd menduner     # 只做一次,之后用 htpasswd -b 加用户
```

站点配置 `location /api/` 里用这张表,并把登录名转发给后端:

```nginx
auth_basic $menduner_deny;
auth_basic_user_file /etc/nginx/.htpasswd;
proxy_set_header X-Menduner-Login $remote_user;
```

`$remote_user` 由 nginx 填写,客户端自己带的同名头会被覆盖,所以不能伪造。

**第二层:后端也拒绝无身份的写**(`backend/auth.py`)。写接口缺少 `X-Menduner-Login` 时返回 **401**,不会静默执行——这样即使哪天 nginx 规则丢了,写接口是"坏掉"而不是"重新开放"。脚本可以带令牌调用:

```bash
# systemd 里设置 MENDUNER_WRITE_TOKEN=<随机串>
curl -u menduner:口令 -X POST http://127.0.0.1/api/review ...        # 浏览器/人
curl -H "Authorization: Bearer $MENDUNER_WRITE_TOKEN" ...            # 脚本
curl -X POST http://127.0.0.1:8000/review ...                        # 直连后端 -> 401
```

> **浏览器提示框**:第一次写操作(审核、合并、保存坐标)会弹认证框,输一次即可。
> **本地开发**:Vite 代理没有 nginx,所以要在 `frontend/.env.local` 写 `MENDUNER_WRITE_LOGIN=local-dev`,代理会把这个名字作为登录名转发;不设就是"陌生人",写操作会 401(这正是线上匿名请求的结果)。
> **只保护 API**:如果想整站都要口令,把 `auth_basic` 加到 `location /` 里。

**部署后自检**(应当看到 401/404,而不是 200):

```bash
curl -o /dev/null -w '%{http_code}\n' -X POST -H 'Content-Type: application/json' -d '{}' \
  http://127.0.0.1/api/review            # 401(nginx)
curl -o /dev/null -w '%{http_code}\n' -X POST -H 'Content-Type: application/json' -d '{}' \
  http://127.0.0.1:8000/review           # 401(后端直连)
```

### 11.1 角色:谁能写、谁只能读

**共享登录区分不了"审核员"和"客户只读"**,所以写操作再按角色放行一次。映射先放配置文件
`backend/roles.json`(可用 `MENDUNER_ROLES_PATH` 指向别处),每个 nginx 账号一条:

```json
{
  "users": {
    "menduner":  { "role": "admin",    "name": "管理员" },
    "reviewer1": { "role": "reviewer", "name": "审核员" },
    "hotel-a":   { "role": "viewer",   "name": "客户只读" }
  }
}
```

| 角色 | 能做什么 |
|---|---|
| `admin` | 全部(含未来账号/授权管理) |
| `reviewer` | 审核证据、合并场馆、录入坐标 |
| `viewer` | 只读;调用写接口返回 **403**(客户账号) |

- **没有条目的账号 = 拒绝**(403),理由:nginx 里可能有本文件未授权的账号。
- 文件缺失或 JSON 损坏 = 全部写操作 403(fail-closed),不会重新开放。
- `GET /auth/me` 返回当前身份与角色,便于前端区分只读界面。
- 加人:**两边都要加**——nginx 账号 + 角色条目:

```bash
sudo htpasswd -b /etc/nginx/.htpasswd reviewer1 '<口令>'
sudo /srv/menduner/venv/bin/python -m json.tool /srv/menduner/backend/roles.json >/dev/null  # 确认格式
sudo systemctl restart menduner-backend   # 角色文件按请求读取,重启只为保险
```

- **审核员建议每人一个账号**:`/venues/edits`、`/review` 记录的 `reviewer` 是签署名,
  而 `authenticated_as` 是实际调用者,两者一起才可追溯。

**页面与接口的边界**(2026-10-18 拆分):

- `/evidence` = **数据质量与来源**,公开只读:来源、字段证据、核验状态、采集来源状态。
  匿名可读,这是信任基础,不要给它加口令。
- `/review` = **审核台**,仅 `reviewer`/`admin`:审核、合并场馆、坐标、前端错误日志。
  导航项只对审核员显示;匿名或客户账号看到 403 说明,而不是一页按钮。
- **内部读接口也按角色校验**(匿名 401、viewer 403):`GET /review`、`GET /review/{id}`、
  `GET /client-errors`、`GET /crawl/runs`、`/venues/duplicates`、`/venues/coordinates/needed`、
  `/venues/edits`、`/api/plan`(商业规划,admin-only)。公开读保持开放:`/dataset`、`/evidence`、`/venues`、`/crawl/health`、`/auth/me`。
- 自检:

```bash
curl -o /dev/null -w '%{http_code}\n' http://127.0.0.1/api/review                    # 401(匿名)
curl -o /dev/null -w '%{http_code}\n' -u liuge:'<口令>' http://127.0.0.1/api/review  # 200
curl -o /dev/null -w '%{http_code}\n' http://127.0.0.1/api/client-errors             # 401(匿名)
```

---

## 12. 日常维护

**看日志**
```bash
journalctl -u menduner-backend -f          # 后端实时日志
tail -f /var/log/nginx/access.log          # 访问日志
```

**重启 / 停止**
```bash
systemctl restart menduner-backend
systemctl stop menduner-backend
```

**备份数据库**（这就是全部家当，建议每周一次）
```bash
cp /srv/menduner/data/menduner.sqlite3 /root/menduner-$(date +%F).sqlite3
```
再下载到本地：
```powershell
scp admin@47.116.133.230:/root/menduner-2026-10-14.sqlite3 .
```

**重新采集数据**（可选，会在服务器上访问外部网站）
```bash
cd /srv/menduner
./venv/bin/python -X utf8 -m crawler.run --max-items 40 --db /srv/menduner/data/menduner.sqlite3
```

> 注意：在云服务器上跑爬虫，出口 IP 是机房 IP，可能被部分站点拦截。演示前建议在本地采集好再上传数据库。

---

## 13. 后面想绑域名

1. 买域名，解析 A 记录到公网 IP
2. **大陆服务器必须 ICP 备案**（2-20 天）——不备案域名访问会被拦
3. 备案通过后把 nginx 配置里的 `server_name` 改成域名
4. 想用 HTTPS 就 `apt install certbot python3-certbot-nginx && certbot --nginx -d 你的域名`
5. **别忘了**把新域名加到高德 Key 的白名单，并重新构建前端

---

## 已知限制（如实说明）

- **68 个活动不上地图**：场馆缺坐标（`山丘livehouse-斜塘店` 等在高德查不到），或场馆引用未经人工确认。这是数据现状，不是部署问题。
- **92MB 第三方原始 HTML** 存在数据库里。内部演示没问题；**公开对外提供浏览可能违反来源站点条款**。若要公开，建议清掉 `crawler_raw_items.raw_content`（能从 105MB 降到 1MB 以内），但会失去"翻回原页"的留证能力。
- **单进程 `--workers 1`**：SQLite 写入并发有限，不要加 workers，会锁冲突。
