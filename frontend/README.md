# Frontend local development

Windows团队首次安装可双击根目录setup.bat（自动执行npm install），日常使用start.bat，服务就绪后自动打开浏览器。完整说明见[README_SETUP.md](../README_SETUP.md)。

现有 React + TypeScript + Vite 前端，保留六页路由、共享布局和本地 API 适配器。

## 环境要求

- **Node.js 22+；使用22系列时至少22.12.0**，以满足本仓库 Vite 7 的要求。
- npm（随 Node.js 安装）。先用 `node --version`、`npm --version` 检查。
- 后端运行在 <http://127.0.0.1:8000>；启动步骤见 [backend/README.md](../backend/README.md)。

## 首次安装

从 Menduner 仓库根目录开始：

```powershell
cd frontend
npm install
```

保留并提交项目的 package-lock.json。需要严格按锁文件重装时可使用 `npm ci`；日常启动不需要重复安装依赖。

## 启动

在 frontend 目录运行：

```powershell
npm run dev
```

打开 <http://localhost:5173>，根路径会进入 `/map`。终端保持运行，Ctrl+C 停止。若5173已被占用，Vite可能选择另一个端口，请查看终端打印的实际地址。

现有路由：`/map`、`/calendar`、`/graph`、`/hotels`、`/insights`、`/evidence`。

Vite 将 `/api` 转发到本机8000端口。API未启动时，页面会显示连接错误；已有快照标注为上次数据，不会自动伪装成实时数据。设置中可显式选择本地 DEMO，适合不启动后端时查看交互。

## 可选：高德地图配置

未配置地图时，列表、日历、图谱与证据仍可使用。需要地图时，在 frontend 目录创建本地配置，**已有文件不要覆盖**：

```powershell
if (!(Test-Path .env.local)) { Copy-Item .env.example .env.local }
notepad .env.local
```

填入自己持有的配置：

```dotenv
VITE_AMAP_KEY=你的Web端JSAPI_Key
VITE_AMAP_SERVICE_HOST=/_AMapService
AMAP_SECURITY_CODE=你的安全密钥
```

`AMAP_SECURITY_CODE` 仅供 Vite 本地代理读取，不能改成 `VITE_` 前缀。`.env.local` 不提交；不要在源码、截图或日志中放入密钥。前端运行不需要 DeepSeek 密钥。

修改配置后重启 npm run dev。真实地图还要求高德权限、域名配置及网络可用；地图失败不影响本地数据链路的运行。

## 检查

在 frontend 目录执行：

```powershell
npm test
npm run build
```

`npm run build` 生成 dist，但不会将后端或开发代理打包进去。完整本地演示请使用 `npm run dev`；`npm run preview` 不提供 `/api` 和高德的开发代理。

## 常见问题

| 现象 | 处理 |
|---|---|
| 找不到 package.json | 确认当前目录是 frontend |
| Node engine / Vite版本错误 | 更新至Node.js 22.12+，重新打开终端，再运行 npm install |
| API不可用 / ECONNREFUSED | 先打开后端 `/docs`，确认8000端口服务运行，再点击“刷新 API 数据” |
| API正常但活动为0条 | 从仓库根目录运行真实采集器并检查报告，然后刷新API数据 |
| 地图提示待配置 | 检查可选高德配置；无需为了运行其余页面填写密钥 |
| localhost地址不通 | 检查开发服务终端是否仍运行，以及Vite实际端口 |
| 安装下载失败 | 检查本机网络与代理后重试；不要删除锁文件来绕过错误 |

`node_modules`、dist、coverage、本地环境文件均不提交。统一工作流见 [根目录 README](../README.md)。
