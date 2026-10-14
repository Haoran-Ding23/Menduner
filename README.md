**Latest V1.6 priority refinement:** [Damai adapter, Huodongjia verification and Expo investigation](docs/V1.6_PRIORITY_SOURCE_REVIEW.md). No additional live events were collected; current limitations remain explicit. The descriptions below record the original V1.6 baseline.

# Menduner — Local Development

Menduner 为酒店行业提供可追溯的城市活动情报和外部需求信号。当前保留 V1.3 应用及六页前端、FastAPI + SQLite 架构，采集管线增量升级为 V1.6，面向学术及企业演示。

## 架构

**有限真实来源 → SQLite Database → FastAPI Backend → React Frontend**

当前crawler目录包含有限真实适配器，测试数据单独放在crawler/demo/。抓取值保持未核验或待复核，MOCK/DEMO不作为真实事实。本项目不预测收入、不自动定价、不替代 RMS。

| 目录 | 用途 |
|---|---|
| frontend/ | React + TypeScript + Vite；六页界面 |
| backend/ | FastAPI + SQLite；Python环境固定为 backend/.venv |
| crawler/ | 独立真实来源、原文、提取、字段证据；demo独立 |
| docs/ | 数据契约及历史验证记录 |
| scripts/ | 现有完整链路冒烟检查 |

没有 Docker、云部署、Neo4j 或认证系统。

## Crawler Pipeline V1.6

CityEvent 来源清单已注册十个 Tier 1 网站，另保留原有两个来源及仅供人工核验的“苏州发布”微信记录。可靠提取与公开页面审计分开，失败保留 reason，不制造活动。使用 `python -m crawler.run --tier1 --max-items 3 --db 独立数据库路径 --coverage-report docs/crawler-v16-coverage.json`。详见 [V1.6 说明](docs/CRAWLER_V1.6.md) 和 [来源覆盖报告](docs/V1.6_SOURCE_COVERAGE_REPORT.md)。前端、API 路由和 SQLite schema 保持不变。

## Crawler Pipeline V1.5 baseline

生产采集现使用苏州市政府公开活动报道、苏交官方演出栏目和上海乐历苏州详情。真实采集保留原文、字段片段、来源与待复核状态；演示适配器移至crawler/demo/，不作为失败回退。详见[crawler/README.md](crawler/README.md)及[真实采集报告](docs/CRAWLER_V1.5_REPORT.md)。前端UI和API路由保持现有版本。

## 团队推荐工作流

使用标准Python3.14.x venv，环境固定为backend/.venv；不使用Anaconda/conda。安装Node.js22.12+后取得团队当前代码版本：首次双击 **setup.bat**，日常双击 **start.bat**，结束双击 **stop.bat**。启动成功后自动打开 http://localhost:5173/map 。

完整步骤见[README_SETUP.md](README_SETUP.md)。environment.yml仅记录环境，不作为conda安装入口；pip依赖以backend/requirements.txt为准。旧版环境迁移与本次验证见[TEAM_SETUP_VALIDATION.md](docs/TEAM_SETUP_VALIDATION.md)。

## 首次设置（手动等价步骤，Windows PowerShell）

克隆仓库并进入根目录；已有仓库直接进入即可，不需要重新克隆：

```powershell
git clone https://github.com/Haoran-Ding23/Menduner.git
cd Menduner
```

以下步骤以当前代码版本为准。确保仓库已包含 backend 和 frontend 文件夹。

### 1. 后端环境

推荐 Python 3.14，先执行 `python --version`。Node.js 要求22+（22系列至少22.12）。

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pip check
cd ..
```

若激活脚本被阻止，直接使用 `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`（在backend目录），不用修改执行策略。CMD激活方式和Linux/macOS步骤见 [后端 README](backend/README.md)。SQLite随Python提供，无需安装数据库服务。

### 2. 可选：真实采集

在仓库根目录执行：

```powershell
.\backend\.venv\Scripts\python.exe -m crawler.run
```

这会读取有限公开真实来源并写入SQLite；需要联网。旧DEMO数据会先备份归档再从活动库移除，详见crawler/README.md。未执行时后端可正常启动，但数据库为空。数据库文件被忽略，不随源码分发。

### 3. 前端依赖

```powershell
cd frontend
npm install
cd ..
```

前端不需要密钥即可打开六页。高德地图为可选配置，见 [前端 README](frontend/README.md)；已有 `.env.local` 请保留。

## Windows 一键启动

完成首次依赖安装后，双击根目录 `start.bat`；结束演示时双击 `stop.bat`。无需手动激活环境或打开两个终端。安装与排障说明见 [README_LOCAL_WINDOWS.md](README_LOCAL_WINDOWS.md)。

## 每日启动（手动方式）

打开两个终端；以下都从 **Menduner仓库根目录**开始。

**终端1：后端（无需激活环境）**

```powershell
.\backend\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload
```

如果已经激活 backend/.venv，也可以直接运行：

```powershell
uvicorn backend.main:app --reload
```

打开 <http://127.0.0.1:8000/docs> 确认API启动。

**终端2：前端**

```powershell
cd frontend
npm run dev
```

打开 <http://localhost:5173>。先启动后端再启动前端，可以避免初次API连接失败。两终端都保持运行；分别用Ctrl+C停止。无需每天重新创建环境或安装依赖。

前端通过本地Vite代理读取API。采集数据变化后点击“刷新 API 数据”；来源数、活动数、核验状态和最后采集时间会同步显示。

## API与检查

浏览器可直接查看 `/events`、`/venues`、`/evidence`、`/status`，通过 `/docs` 测试全部接口。接口详细契约见 [API_AND_DATA.md](docs/API_AND_DATA.md)。

```powershell
# 仓库根目录；无需事先启动服务器
.\backend\.venv\Scripts\python.exe -m pytest backend\tests -q

# 完整链路检查：先停止占用8000/5173端口的本项目服务
.\backend\.venv\Scripts\python.exe scripts\smoke_pipeline.py

cd frontend
npm test
npm run build
```

冒烟脚本使用临时数据库，不覆盖默认数据库，并自动关闭自身启动的服务。`npm run build` 只生成静态页面；完整演示使用开发服务，不能把 npm run preview 当成带API代理的服务。

## 排障

| 问题 | 检查 |
|---|---|
| No module named backend | 启动命令应在仓库根目录执行，而非backend内 |
| FastAPI / Uvicorn找不到 | 使用 backend/.venv 中的解释器；确认requirements安装成功 |
| PowerShell无法激活 | 使用免激活完整解释器路径，不必修改全局执行策略 |
| Node版本不兼容 | 使用Node.js 22.12+；更新后重新打开终端 |
| 前端显示API不可用 | 打开8000端口的/docs检查后端，然后刷新API数据 |
| 活动为空 | 空库不自动填充；运行真实采集器并检查报告，确认MENDUNER_DB_PATH一致 |
| 端口占用 | 确认是否已有本项目服务在运行；不要随意结束未知进程 |
| 地图不可用 | 查看前端README的可选高德配置；不影响其他页面和API测试 |
| 旧的根目录.venv仍存在 | 可保留，新命令统一使用backend/.venv；避免解释器混用 |

## 本地文件与凭据

Git忽略 backend/.venv、frontend/node_modules、构建产物、`.env`及其本地变体、SQLite数据库与日志。只提交 `.env.example` 这样的空白配置模板。不要提交API密钥、数据库或虚拟环境。

忽略规则不会自动移除之前已跟踪的文件；提交前执行 `git status --short`，确认改动范围。环境、数据库和凭据分别留在本机，不需要云服务或额外密钥即可运行核心演示。

本次操作整理不修改业务逻辑、UI或pip依赖版本；Python运行时统一为3.14.x。本次验证范围见 [TEAM_SETUP_VALIDATION.md](docs/TEAM_SETUP_VALIDATION.md)；V1.1–V1.3旧文档中的根目录 `.venv` 命令以本README的新路径为准。
