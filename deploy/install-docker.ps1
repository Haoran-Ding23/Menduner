# 一键安装 WSL2 + Docker Desktop（需要一次管理员授权）
#
# 双击本文件即可：脚本会自己请求管理员权限（UAC 弹窗点「是」），然后依次：
#   1. 启用 WSL2（含虚拟机平台组件）
#   2. 安装 Docker Desktop
#   3. 报告是否需要重启
#
# 为什么不能由 AI 代做：UAC 授权框必须由人点击，普通权限进程无法自我提权。

$ErrorActionPreference = 'Stop'

function Test-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-Admin)) {
    Write-Host '需要管理员权限，正在请求授权（请在弹窗中点「是」）...' -ForegroundColor Yellow
    $arguments = @(
        '-NoProfile',
        '-ExecutionPolicy', 'Bypass',
        '-File', ('"{0}"' -f $PSCommandPath)
    )
    Start-Process -FilePath 'powershell.exe' -ArgumentList $arguments -Verb RunAs
    exit
}

Write-Host '=== 已获得管理员权限 ===' -ForegroundColor Green

# ---------------------------------------------------------------- WSL2
Write-Host "`n[1/3] 安装 WSL2 ..." -ForegroundColor Cyan
$wsl = Get-Command wsl -ErrorAction SilentlyContinue
if ($wsl) {
    $status = & wsl --status 2>&1 | Out-String
    if ($status -match '默认版本|Default Version') {
        Write-Host '  WSL 已安装，跳过。' -ForegroundColor Green
    } else {
        & wsl --install --no-distribution
    }
} else {
    & wsl --install --no-distribution
}
Write-Host "  WSL 组件处理完成（若提示需要重启，重启后继续第 2 步）。"

# ---------------------------------------------------------------- Docker Desktop
Write-Host "`n[2/3] 安装 Docker Desktop ..." -ForegroundColor Cyan
$docker = Get-Command docker -ErrorAction SilentlyContinue
if ($docker) {
    Write-Host '  已检测到 docker 命令，跳过安装。' -ForegroundColor Green
} else {
    & winget install -e --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements
}

# ---------------------------------------------------------------- 验证
Write-Host "`n[3/3] 验证 ..." -ForegroundColor Cyan
$dockerCmd = Get-Command docker -ErrorAction SilentlyContinue
if ($dockerCmd) {
    & docker --version
    Write-Host '  Docker CLI 可用。启动 Docker Desktop 后，用 docker compose version 复核。' -ForegroundColor Green
} else {
    Write-Host '  未检测到 docker：可能需要重启一次再运行本脚本的第二阶段。' -ForegroundColor Yellow
}

Write-Host "`n完成。若刚安装了 WSL，请重启电脑，然后启动 Docker Desktop。" -ForegroundColor Green
Write-Host '重启后在本项目目录运行：' -ForegroundColor Gray
Write-Host '  docker compose -f deploy/docker-compose.yml up --build' -ForegroundColor Gray
Write-Host '  # 打开 http://localhost:8080' -ForegroundColor Gray
Read-Host "`n按回车关闭"
