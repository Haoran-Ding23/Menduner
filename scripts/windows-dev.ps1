# Windows PowerShell 5.1 helper for the setup/start/stop batch entry points.
[CmdletBinding()]
param(
    [ValidateSet('Setup', 'Start', 'Stop', 'Backend', 'Frontend')]
    [string]$Action = 'Start',
    [string]$Token = ''
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$statePath = Join-Path $projectRoot '.menduner-dev.json'
$helperPath = $PSCommandPath

function Read-State {
    if (Test-Path -LiteralPath $statePath) {
        return Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    }
    return $null
}
function Save-State($State) {
    $tempPath = "$statePath.tmp"
    $State | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $tempPath -Encoding UTF8
    Move-Item -LiteralPath $tempPath -Destination $statePath -Force
}
function Get-OwnedProcess($Entry, $State) {
    if (-not $Entry -or -not $State.token) { return $null }
    $processId = [int]$Entry.processId
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $processId" -ErrorAction Stop
    if ($process -and $process.CommandLine -and
        $process.CommandLine.Contains([string]$State.token) -and
        $process.CommandLine.Contains([string]$State.helperPath) -and
        $process.Name -ieq 'powershell.exe') { return $process }
    return $null
}
function Stop-OwnedServices($State) {
    if (-not $State) { return }
    foreach ($entry in @($State.processes)) {
        $owned = Get-OwnedProcess $entry $State
        if ($owned) {
            Write-Host "正在停止 Menduner $($entry.role) 终端及其服务进程树..."
            & "$env:SystemRoot\System32\taskkill.exe" /PID $owned.ProcessId /T /F
            if ($LASTEXITCODE -ne 0 -and (Get-OwnedProcess $entry $State)) {
                throw '有 Menduner 进程无法停止。状态已保留，请再次运行 stop.bat。'
            }
        }
    }
    Remove-Item -LiteralPath $statePath -Force -ErrorAction SilentlyContinue
}
function Assert-FreePorts {
    foreach ($port in @(8000, 5173)) {
        $listeners = [System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()
        if (@($listeners | Where-Object { $_.Port -eq $port }).Count -gt 0) {
            throw "端口 $port 已被占用。请先停止已有服务，未终止任何进程。"
        }
    }
}
function Test-Python314([string]$Executable, [string[]]$PrefixArgs = @(), [switch]$RequireVenv) {
    $code = "import sys, os; assert sys.version_info[:2] == (3,14); assert not os.path.isdir(os.path.join(sys.base_prefix, 'conda-meta'))"
    if ($RequireVenv) { $code += "; assert sys.prefix != sys.base_prefix" }
    try {
        & $Executable @PrefixArgs -c $code 2>$null | Out-Null
        return $LASTEXITCODE -eq 0
    } catch { return $false }
}
function Resolve-Environment {
    $python = Join-Path $projectRoot 'backend\.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw '缺少 backend\.venv，请先运行 setup.bat。' }
    if (-not (Test-Python314 -Executable $python -RequireVenv)) {
        throw 'backend\.venv 必须使用标准 Python 3.14.x 的 venv。请先把旧环境改名保留，然后重新运行 setup.bat；参见 README_SETUP.md。'
    }
    & $python -c 'import fastapi, uvicorn, sqlite3' | Out-Host
    if ($LASTEXITCODE -ne 0) { throw '后端依赖缺失，请运行 setup.bat。' }
    return @{ kind = 'venv'; executable = $python }
}
function Get-Npm {
    if (-not (Get-Command node.exe -ErrorAction SilentlyContinue)) { throw '未找到 Node.js。请安装 Node.js 22.12+ 后重新打开启动器。' }
    $nodeVersion = & node.exe -p 'process.versions.node'
    if ($LASTEXITCODE -ne 0 -or [version]$nodeVersion -lt [version]'22.12.0') { throw '需要 Node.js 22.12+。' }
    $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if (-not $npm) { throw '未找到 npm.cmd。请安装带 npm 的 Node.js。' }
    return $npm.Source
}
function Install-Environment {
    Set-Location -LiteralPath $projectRoot
    $npm = Get-Npm
    $venvPath = Join-Path $projectRoot 'backend\.venv'
    $python = Join-Path $venvPath 'Scripts\python.exe'
    if (Test-Path -LiteralPath $venvPath) {
        if (-not (Test-Path -LiteralPath $python) -or -not (Test-Python314 -Executable $python -RequireVenv)) {
            throw '现有 backend\.venv 不完整，或不是标准 Python 3.14。未对它做任何修改。参见 README_SETUP.md 保留它并创建新环境。'
        }
    } else {
        $selected = $null
        $prefixArgs = @()
        $command = Get-Command python.exe -ErrorAction SilentlyContinue
        if ($command -and (Test-Python314 -Executable $command.Source)) { $selected = $command.Source }
        if (-not $selected) {
            $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
            if ($launcher -and (Test-Python314 -Executable $launcher.Source -PrefixArgs @('-3.14'))) {
                $selected = $launcher.Source
                $prefixArgs = @('-3.14')
            }
        }
        if (-not $selected) { throw '未找到标准 Python 3.14.x。请安装并加入 PATH，然后重新运行 setup.bat；也支持 Python Launcher 的 py -3.14。' }
        & $selected @prefixArgs -m venv $venvPath
        if ($LASTEXITCODE -ne 0) { throw '创建虚拟环境失败。请检查 Python 安装和文件夹权限。' }
    }
    Write-Host '正在安装后端依赖...'
    & $python -m pip install -r (Join-Path $projectRoot 'backend\requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw '后端安装失败。请修复上面报告的网络或软件包错误，然后重新运行 setup.bat。' }
    & $python -m pip check
    if ($LASTEXITCODE -ne 0) { throw '后端依赖校验失败。' }
    $null = Resolve-Environment
    Write-Host '正在安装前端依赖...'
    Push-Location -LiteralPath (Join-Path $projectRoot 'frontend')
    try {
        & $npm install
        if ($LASTEXITCODE -ne 0) { throw '前端安装失败。请修复上面报告的 npm 错误，然后重新运行 setup.bat。' }
    } finally { Pop-Location }
    Write-Host '安装完成。日常使用请双击 start.bat。' -ForegroundColor Green
}
function Get-ServiceLogPath([string]$Role) {
    return (Join-Path $projectRoot ('.menduner-{0}.log' -f $Role.ToLowerInvariant()))
}
# Service terminals append a MENDUNER-SERVICE-EXITED marker when their service process is gone.
# Reading the marker lets the coordinator stop waiting at once instead of burning the whole deadline.
function Get-ServiceStoppedDetail([string]$LogPath) {
    if (-not (Test-Path -LiteralPath $LogPath)) { return $null }
    try { $tail = @(Get-Content -LiteralPath $LogPath -Tail 8 -ErrorAction Stop) } catch { return $null }
    if ($tail.Count -eq 0) { return $null }
    if ([string]$tail[-1] -notlike '*MENDUNER-SERVICE-EXITED*') { return $null }
    $detail = @($tail | Where-Object { $_ -notlike '*MENDUNER-SERVICE-EXITED*' })
    if ($detail.Count -eq 0) { return '服务在退出前没有任何输出。' }
    return (($detail | Select-Object -Last 6) -join [Environment]::NewLine)
}
# Streams a service's stdout/stderr lines into the terminal window and its log file.
# Start-Transcript never captured these native streams, which is why the logs used to be header-only.
function Add-ServiceOutput {
    param(
        [Parameter(Mandatory = $true)][string]$LogPath,
        [Parameter(ValueFromPipeline = $true)][AllowNull()]$InputObject
    )
    process {
        $line = if ($InputObject -is [System.Management.Automation.ErrorRecord]) { $InputObject.Exception.Message } else { [string]$InputObject }
        Write-Host $line
        Add-Content -LiteralPath $LogPath -Value $line -Encoding UTF8
    }
}
function Wait-Http([string]$Url, [int]$TimeoutSec = 40, [string]$ServiceLog = '') {
    # The deadline is a ceiling for a live-but-slow service: a service that exits is detected on the
    # next poll, so a generous ceiling never turns a diagnosed failure into a full-window hang.
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -eq 200) { return $response }
        } catch { }
        if ($ServiceLog) {
            $detail = Get-ServiceStoppedDetail $ServiceLog
            if ($detail) {
                throw ("服务在 $Url 响应之前已退出。$(Split-Path -Leaf $ServiceLog) 的最后几行：" + [Environment]::NewLine + $detail)
            }
        }
        Start-Sleep -Milliseconds 300
    }
    throw "等待 $Url 超时。请查看服务终端或 .menduner-backend.log / .menduner-frontend.log。"
}
function Start-Terminal([string]$Role, $State) {
    # A single quoted argument string preserves repository paths containing spaces.
    $arguments = '-NoLogo -NoProfile -NoExit -ExecutionPolicy Bypass -File "{0}" -Action {1} -Token {2}' -f $helperPath, $Role, $State.token
    $child = Start-Process -FilePath "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -ArgumentList $arguments -WorkingDirectory $projectRoot -PassThru
    $State.processes += @{ role = $Role; processId = $child.Id }
    Save-State $State
}

# Workers stay in their dedicated visible terminals. They never acquire the coordinator lock.
if ($Action -in @('Backend', 'Frontend')) {
    $logPath = Get-ServiceLogPath $Action
    function Write-ServiceLog([string]$Message, [string]$Color = 'Gray') {
        $line = '{0} {1}' -f (Get-Date -Format 'HH:mm:ss'), $Message
        Write-Host $line -ForegroundColor $Color
        Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
    }
    try {
        $state = Read-State
        if (-not $state -or $Token -ne $state.token) { throw '启动器状态缺失或已过期，请重新运行 start.bat。' }
        $Host.UI.RawUI.WindowTitle = "Menduner $Action"
        Write-ServiceLog "Menduner $Action 正在启动，服务输出将写入 $(Split-Path -Leaf $logPath)。"
        # Native services write to stdout/stderr, which Start-Transcript never recorded. Decode that
        # output as UTF-8 and tee every line into this window and into the log file.
        [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
        $ErrorActionPreference = 'Continue'
        if ($Action -eq 'Backend') {
            Set-Location -LiteralPath $projectRoot
            & $state.environment.executable -m uvicorn backend.main:app --reload 2>&1 | Add-ServiceOutput -LogPath $logPath
        } else {
            Set-Location -LiteralPath (Join-Path $projectRoot 'frontend')
            # Keep 5173 fixed: never silently switch to a different port during presentations.
            & $state.npm run dev '--' '--port' '5173' '--strictPort' 2>&1 | Add-ServiceOutput -LogPath $logPath
        }
        $exitCode = $LASTEXITCODE
        if ($exitCode -ne 0) { Write-ServiceLog "$Action 已退出，退出代码 $exitCode。" 'Red' }
        else { Write-ServiceLog '服务已停止。使用 stop.bat 关闭启动器终端。' }
    } catch {
        Write-ServiceLog $_.Exception.Message 'Red'
    } finally {
        # Marker line the coordinator polls: the service process is gone, so stop waiting immediately.
        Write-ServiceLog "#MENDUNER-SERVICE-EXITED# $Action"
    }
    return
}

$mutex = $null
$locked = $false
$startedState = $null
try {
    $hash = [System.Security.Cryptography.SHA256]::Create()
    try { $key = [BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($projectRoot.ToLowerInvariant()))).Replace('-', '') }
    finally { $hash.Dispose() }
    $mutex = New-Object System.Threading.Mutex($false, "Local\Menduner-$key")
    try { $locked = $mutex.WaitOne(0) }
    catch [System.Threading.AbandonedMutexException] { $locked = $true }
    if (-not $locked) { throw '另一个 Menduner 安装/启动/停止操作正在运行，请等待它结束。' }
    $state = Read-State
    if ($Action -eq 'Setup') {
        if ($state) {
            foreach ($entry in @($state.processes)) {
                if (Get-OwnedProcess $entry $state) { throw '安装依赖前请先用 stop.bat 停止 Menduner。' }
            }
        }
        Assert-FreePorts
        Install-Environment
    } elseif ($Action -eq 'Stop') {
        if ($state) { Stop-OwnedServices $state; Write-Host 'Menduner 启动器服务已停止。' }
        else { Write-Host '没有记录到由启动器管理的服务，未终止任何进程。' }
    } else {
        if ($state) {
            foreach ($entry in @($state.processes)) {
                if (Get-OwnedProcess $entry $state) { throw 'Menduner 已在启动器终端中运行，请先运行 stop.bat 再重新启动。' }
            }
            Remove-Item -LiteralPath $statePath -Force
        }
        Assert-FreePorts
        if (-not (Test-Path -LiteralPath (Join-Path $projectRoot 'frontend\package.json'))) { throw '缺少 frontend\package.json，请把启动器放在仓库根目录。' }
        $npmPath = Get-Npm
        if (-not (Test-Path -LiteralPath (Join-Path $projectRoot 'frontend\node_modules\vite\bin\vite.js'))) { throw '前端依赖缺失，请先在 frontend 目录运行 npm install。' }
        $environment = Resolve-Environment
        $startedState = @{ token = [Guid]::NewGuid().ToString('N'); helperPath = $helperPath; environment = $environment; npm = $npmPath; processes = @() }
        Save-State $startedState
        Write-Host "后端环境：$($environment.kind)"
        $backendLog = Get-ServiceLogPath 'Backend'
        Remove-Item -LiteralPath $backendLog -Force -ErrorAction SilentlyContinue
        Start-Terminal 'Backend' $startedState
        $null = Wait-Http 'http://127.0.0.1:8000/docs' -TimeoutSec 90 -ServiceLog $backendLog
        $frontendLog = Get-ServiceLogPath 'Frontend'
        Remove-Item -LiteralPath $frontendLog -Force -ErrorAction SilentlyContinue
        Start-Terminal 'Frontend' $startedState
        # Vite binds 127.0.0.1 only (see frontend/vite.config.ts). Windows PowerShell resolves
        # "localhost" to ::1 first and never retries 127.0.0.1, so probing "localhost" never answered.
        $null = Wait-Http 'http://127.0.0.1:5173/' -TimeoutSec 120 -ServiceLog $frontendLog
        $response = Wait-Http 'http://127.0.0.1:5173/api/dataset' -TimeoutSec 60 -ServiceLog $frontendLog
        $dataset = $response.Content | ConvertFrom-Json
        if (-not ($dataset.PSObject.Properties.Name -contains 'events') -or -not $dataset.status) { throw '前端代理未返回预期的 Menduner API 数据集。' }
        Write-Host 'Menduner 已就绪：后端、前端以及前端到 API 的检查均已通过。' -ForegroundColor Green
        Write-Host '后端：http://127.0.0.1:8000'
        Write-Host 'API 文档：http://127.0.0.1:8000/docs'
        Write-Host '前端：http://localhost:5173'
        Write-Host '双击 stop.bat 可停止两个服务进程树。'
        try { Start-Process 'http://localhost:5173/map' }
        catch { Write-Warning '服务已就绪，但浏览器无法打开。请手动访问 http://localhost:5173/map。' }
    }
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    if ($startedState) {
        try { Stop-OwnedServices $startedState }
        catch { Write-Host "清理失败：$($_.Exception.Message)" -ForegroundColor Red }
    }
    exit 1
} finally {
    if ($locked) { $mutex.ReleaseMutex() }
    if ($mutex) { $mutex.Dispose() }
}
