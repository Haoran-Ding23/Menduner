# Menduner 团队环境设置

统一环境：**标准 Python 3.14.x + Python venv + Node.js 22.12+ + npm**。不使用 Anaconda 或 conda 创建、安装、激活或启动环境。现有六页前端、API、数据库结构和爬虫逻辑不变。

## 新成员最短流程（Windows）

1. 安装标准Python 3.14.x（启用PATH或Python Launcher）、Node.js 22.12+和Git。
2. 克隆团队共享的、包含这些启动文件的代码版本，然后进入仓库。
3. 双击 **setup.bat**，首次安装依赖，看到 Setup completed 后再继续。
4. 双击 **start.bat**，打开两个服务终端；连通性检查通过后自动打开浏览器地图页。
5. 结束时双击 **stop.bat**。

```powershell
git clone https://github.com/Haoran-Ding23/Menduner.git
cd Menduner
```

如果共享版本尚未合并到默认分支，请先切换到团队发布的分支，或应用随交付包提供的补丁。不要假设远程main已包含本次本地修改。

## setup.bat 做什么

- 从脚本位置识别仓库，不依赖双击时的当前目录。
- 检查Node.js及npm.cmd；Python优先检查PATH中的python.exe，必要时检查 `py -3.14`。
- 创建 `backend/.venv`；只接受标准Python3.14.x，不接受基于conda的解释器。
- 执行虚拟环境中的 `python -m pip install -r backend/requirements.txt`，随后执行pip check及核心模块导入检查。
- 在frontend执行 `npm install`，安装成功后才显示完成。
- 失败时保留错误信息并返回非零退出码；修复网络、版本或权限后可重跑，不会把部分安装显示为成功。

不会自动安装系统Python/Node，不写入密钥、不初始化演示数据，也不修改业务源码。安装过程中需要访问Python/npm包源。运行中的本项目服务需要先用stop.bat停止。

## 手动等价步骤（仓库根目录）

先用 `python --version` 确认输出3.14.x，再执行：

```powershell
python -m venv backend/.venv
.\backend\.venv\Scripts\Activate.ps1
python -m pip install -r backend/requirements.txt
python -m pip check
cd frontend
npm install
cd ..
```

如系统默认Python不是3.14，可将创建命令改为 `py -3.14 -m venv backend/.venv`。如果PowerShell不允许激活，直接调用环境解释器即可，不必修改全局执行策略：

```powershell
.\backend\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
```

### 已有旧环境

setup.bat会重用有效的3.14 venv。对于旧3.12/3.13、conda派生或损坏环境，会停止并提示，不自动删除。

先关闭服务，再将旧环境保留到另一个名字，例如：

```powershell
Rename-Item backend\.venv .venv-old
```

确认该备份名尚不存在后执行，再运行setup.bat。数据库在backend/data，不需要删除。备份环境仅用于保留，虚拟环境移动后不保证可以继续执行。backend/.venv-*已加入Git忽略。

## 环境文件

`backend/requirements.txt` 是权威pip依赖列表，沿用已有固定版本。

`environment.yml` 是**团队参考清单，不是安装入口**。按要求使用name/dependencies/pip结构，列出Python3.14、SQLite及requirements中的全部包。不要运行conda env create；实际安装始终使用venv和pip。

SQLite由标准Python的sqlite3模块提供，不需要安装pip sqlite3包，也不需要独立数据库服务器。YAML中的sqlite只是对原生库依赖的说明。

## 每日运行

双击start.bat，无需激活环境或进入Anaconda Prompt。实际后端命令从仓库根目录运行：

```powershell
.\backend\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload
```

前端从frontend目录运行 `npm.cmd run dev -- --port 5173 --strictPort`，使用额外参数固定展示端口。检查通过后自动打开 <http://localhost:5173/map>。

| 地址 | 用途 |
|---|---|
| http://127.0.0.1:8000/docs | FastAPI接口文档 |
| http://127.0.0.1:8000/status | 数据库状态 |
| http://localhost:5173 | 前端，默认进入地图 |
| http://localhost:5173/api/dataset | 通过前端代理读取API快照 |

后端根路径可能返回404，这是既有接口设计；请用/docs检查。启动器会自动验证/docs、前端首页和/api/dataset。默认浏览器打开失败时保留已就绪服务，并提供手动地址。

## 真实数据和可选地图

初始数据库为空时页面会显示0条；并非启动失败。需要采集有限真实活动时，从根目录执行：

```powershell
.\backend\.venv\Scripts\python.exe -m crawler.run
```

随后在前端点击“刷新 API 数据”。真实抓取字段仍保持未核验/待复核；旧DEMO先备份归档。高德配置是可选项，见frontend/README.md。现有.env.local请保留，不要分享密钥。

## 停止与排障

stop.bat只停止当前仓库启动器记录的终端和进程树，包括Uvicorn重载进程和Node/Vite。手动启动的服务需到原终端按Ctrl+C。不要删除正在使用的.menduner-dev.json状态文件。

| 问题 | 处理 |
|---|---|
| Python3.14找不到 | 安装标准Python3.14并启用PATH，或确认py -3.14可用 |
| 旧venv版本不符 | 保留旧环境到未占用的备份名，再执行setup.bat |
| Node/npm找不到 | 安装Node.js22.12+，重新运行脚本 |
| pip/npm安装失败 | 保留终端错误，检查网络或代理后重跑setup.bat |
| 端口8000/5173占用 | 停止自己的旧服务；启动器不强杀未知占用者 |
| setup提示服务运行中 | 先stop.bat，再setup.bat |
| 地图未配置 | 不影响其余页面；按前端说明填写可选配置 |
| API不可用 | 查看.menduner-backend.log及.menduner-frontend.log，或直接访问/docs |

Python环境、node_modules、数据库、环境配置和启动日志均不提交。无Docker、云部署、CI/CD、认证或生产配置。

## 验证范围

见docs/TEAM_SETUP_VALIDATION.md。Windows双击安装、窗口管理和浏览器打开需在真实Windows机器验收；Linux上的服务验证不能替代此项。
