# 本地开发环境整理验证

基线：Menduner V1.3，提交 `32c542b`。本次仅修改忽略规则、运行说明及 requirements 注释，没有修改业务源码、UI、依赖版本或数据库结构。

## 已完成检查

| 项目 | 结果 |
|---|---|
| 创建 backend/.venv | Python 3.12.14 创建成功 |
| 新环境安装 backend/requirements.txt | 安装成功，保留 V1.3 固定版本 |
| 新环境 python -m pip check | No broken requirements found |
| 新环境运行后端测试 | 8项通过 |
| 新环境运行现有冒烟脚本 | CLI采集、临时SQLite、FastAPI、Vite代理及六路由HTML壳通过 |
| 仓库根目录运行 uvicorn backend.main:app --reload | 启动成功，/docs HTTP200，空库/events返回[] |
| Git忽略规则 | backend/.venv、frontend/node_modules、.env、.env.local、*.db及事务文件命中忽略规则 |
| Node最低版本依据 | 当前安装的Vite包engines声明要求Node22系列至少22.12；验证机Node24.19 |

## 验证范围

执行环境为Linux；Windows CMD/PowerShell命令已在文档中分别说明，但没有在真实Windows机器执行。未重新运行全套前端测试或视觉测试，因为本次没有修改前端源码；现有HTTP冒烟确认服务与路由仍可运行。

Python测试保留一条上游Starlette/httpx弃用提示，测试通过。本次不为消除提示而更改依赖。

虚拟环境、数据库、node_modules、环境配置和凭据不进入提交或交付包。新开发者需按README在本机生成环境并安装依赖。旧根目录.venv未删除，新文档统一使用backend/.venv。
