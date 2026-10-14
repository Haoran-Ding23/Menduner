# Windows 一键使用

当前团队统一使用标准 **Python 3.14.x venv**，不再支持Anaconda/conda回退。环境位于backend/.venv。

完整安装、升级及排障说明以 [README_SETUP.md](README_SETUP.md) 为准。

1. 安装Python3.14.x、Node.js22.12+和Git，取得当前团队代码版本。
2. 首次双击根目录 **setup.bat**：自动创建venv并安装前后端依赖。
3. 日常双击 **start.bat**：打开后端和前端两个专用终端，检查API连通性，自动打开 http://localhost:5173/map 。
4. 结束双击 **stop.bat**：停止本启动器记录的Uvicorn与Node/Vite进程树。

后端文档：http://127.0.0.1:8000/docs 。前端：http://localhost:5173 。后端根路径/返回404不代表服务故障。

首次安装可能需要几分钟。失败时会明确报错，不显示安装完成；修复问题后重跑setup.bat。已有旧Python环境不会自动删除，迁移步骤见README_SETUP.md。

脚本从自身位置识别项目目录，支持带空格路径。安装和启动均不需要手动激活环境。首次使用前必须已安装系统Python/Node；脚本不下载这些系统程序。

端口8000或5173被占用时停止启动，不会强制结束占用者。重复启动被拒绝，重复停止为安全空操作。运行中的服务窗口只用于本项目，请勿运行其它工作。

状态文件.menduner-dev.json用于核对终端PID、随机会话标识及脚本路径；stop.bat仅停止核对匹配的进程树。手动启动的服务在其原终端按Ctrl+C。服务运行时不要删除状态文件或移动项目。

日志：.menduner-backend.log、.menduner-frontend.log。日志、状态、数据库、虚拟环境、node_modules和本地配置均不分享或提交。

三个BAT入口依赖同目录仓库内的scripts/windows-dev.ps1，请勿单独移动BAT文件。PowerShell策略参数仅针对该子进程，组织强制策略仍按本机管理要求处理。

验证结果及Windows实机待验项目见docs/TEAM_SETUP_VALIDATION.md。
