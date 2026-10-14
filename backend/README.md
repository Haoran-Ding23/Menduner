# Backend local development

Windows首次安装推荐双击根目录setup.bat；日常使用start.bat/stop.bat。详见[README_SETUP.md](../README_SETUP.md)。只使用标准Python venv，不使用Anaconda/conda。

FastAPI + Uvicorn + SQLite。团队统一 **Python 3.14.x**。SQLite 来自 Python 标准库 `sqlite3`，无需单独安装数据库服务或名为 sqlite 的 pip 包。

以下命令从克隆后的 **Menduner 仓库根目录**开始。虚拟环境统一放在 `backend/.venv`；不要复制或提交别人机器上的虚拟环境。

## 首次创建环境（Windows）

先运行 `python --version`，确认使用 Python 3.14。若机器安装了多个版本，可将创建命令换为 `py -3.14 -m venv .venv`。

**Windows CMD：**

```bat
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m pip check
```

**Windows PowerShell：**

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pip check
```

如果 PowerShell 禁止运行激活脚本，可以完全不激活，直接指定解释器；无需修改系统执行策略：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
```

`requirements.txt` 保留 V1.3 已验证的固定版本，包括运行和测试依赖；这次环境整理不升级依赖。

## 启动后端

**重要：`backend.main` 是从仓库根目录导入的包。创建环境后，请从 backend 返回上一级再启动。**

已激活环境时：

```powershell
cd ..
uvicorn backend.main:app --reload
```

等价的免激活方式（从仓库根目录）：

```powershell
.\backend\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload
```

API 文档：<http://127.0.0.1:8000/docs>。默认只监听本机，使用端口8000；前端代理指向此端口。保持终端运行，按 Ctrl+C 停止服务。

启动时会自动创建默认数据库 `backend/data/menduner.sqlite3` 及空表。空数据库是正常状态，后端不会自动填入演示活动。

## 可选：有限真实采集

在仓库根目录的另一个终端执行：

```powershell
.\backend\.venv\Scripts\python.exe -m crawler.run
```

这会运行V1.5有限真实适配器，需要联网；没有MOCK回退。旧演示数据先备份归档，详见crawler/README.md。重复运行会更新同一真实来源，不重复累加事件。前端点击“刷新 API 数据”查看变化。

需要独立测试数据库时，在启动/采集进程前设置 `MENDUNER_DB_PATH` 为完整文件路径。两进程必须使用相同路径。例如 PowerShell：

```powershell
$env:MENDUNER_DB_PATH = "C:\Users\your-name\Menduner-demo.sqlite3"
```

数据库可含本地数据；不要为排障随意删除。它与环境文件均被 Git 忽略。

## API 测试

在浏览器打开 `/docs`，展开接口后选择 **Try it out → Execute**。也可直接访问：

- <http://127.0.0.1:8000/events>
- <http://127.0.0.1:8000/venues>
- <http://127.0.0.1:8000/evidence>
- <http://127.0.0.1:8000/status>

PowerShell：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/status
Invoke-RestMethod http://127.0.0.1:8000/events
```

未采集时活动返回空数组；采集后用 `/events` 返回的真实事件ID测试 `/events/{id}`。不存在的活动返回404。

从仓库根目录执行自动化测试（无需启动服务器）：

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend\tests -q
```

## macOS / Linux

从仓库根目录：

```bash
cd backend
python3.14 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip check
cd ..
uvicorn backend.main:app --reload
```

免激活时使用 `backend/.venv/bin/python`。`python3.14` 不存在时先安装 Python 3.14，或确认 `python3 --version` 后使用对应解释器。

## 日常启动与排障

- 已建环境无需每天重新创建。仓库根目录执行免激活启动命令即可。
- `No module named backend`：当前目录应包含 backend 文件夹；不要在 backend 内运行根目录启动命令。
- `uvicorn` 找不到或 `No module named fastapi`：使用上面的虚拟环境完整解释器路径，并安装 requirements.txt。
- 端口8000被占用：先确认是否已有本项目后端运行。关闭自己不再使用的服务后再试，不要随意结束不认识的进程。
- 前端显示0条：查看 `/status`，确认运行过真实采集器并检查报告且数据库路径一致。
- 项目目录移动后环境失效：保留数据库和配置，重新创建 backend/.venv；虚拟环境不应跨机器复制。
- 旧仓库根目录 `.venv` 可以暂时保留；新命令统一使用 backend/.venv，避免解释器混用。
