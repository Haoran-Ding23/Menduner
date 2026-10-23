@echo off
rem One-time setup for the Xiaohongshu collection toolchain on a NEW machine.
rem Google Chrome is NOT required: Playwright ships its own Chromium.
rem Prerequisite: git and Python 3.12 installed (py -3.12 must work).
rem
rem This script bootstraps tools\MediaCrawler (an upstream MediaCrawler clone that is
rem NOT tracked in this repository — see README.md): clones it if missing, overlays
rem this folder's tuned config and launcher, then builds the venv and downloads
rem Chromium. After it finishes, double-click tools\MediaCrawler\run_xhs.cmd.
setlocal
cd /d %~dp0

py -3.12 --version >nul 2>nul
if errorlevel 1 (
  echo [x] Python 3.12 not found. Install it from python.org, then re-run.
  pause
  exit /b 1
)
for /f "delims=" %%v in ('py -3.12 --version') do echo [0/4] %%v found.

git --version >nul 2>nul
if errorlevel 1 (
  echo [x] git not found. Install git for Windows (git-scm.com), then re-run.
  pause
  exit /b 1
)

if not exist MediaCrawler\main.py (
  echo [1/4] Cloning MediaCrawler via the ghfast mirror...
  git -c http.sslBackend=schannel clone --depth 1 https://ghfast.top/https://github.com/NanmiCoder/MediaCrawler.git MediaCrawler
  if errorlevel 1 (
    echo [x] Clone failed. Check the network and re-run.
    pause
    exit /b 1
  )
) else (
  echo [1/4] MediaCrawler clone already present.
)
copy /y "%~dp0base_config.py" MediaCrawler\config\base_config.py >nul
copy /y "%~dp0run_xhs.cmd" MediaCrawler\run_xhs.cmd >nul
echo [2/4] Tuned config and launcher overlaid.

rem All caches and temp dirs are pinned inside the clone: several machines deny
rem subprocess writes under the user profile (AppData\Local), so never use defaults.
set PIP_CACHE_DIR=%~dp0MediaCrawler\.pipcache
set TMP=%~dp0MediaCrawler\.tmp
set TEMP=%~dp0MediaCrawler\.tmp
set PLAYWRIGHT_BROWSERS_PATH=%~dp0MediaCrawler\.pw-browsers
set MPLCONFIGDIR=%~dp0MediaCrawler\.mplcache

if not exist MediaCrawler\.venv (
  echo [3/4] Creating virtualenv...
  py -3.12 -m venv MediaCrawler\.venv
)
echo [3/4] Installing dependencies (Tsinghua mirror)...
MediaCrawler\.venv\Scripts\python.exe -m pip install -r MediaCrawler\requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --quiet
if errorlevel 1 (
  echo [x] pip install failed. Check the network and re-run.
  pause
  exit /b 1
)
echo [4/4] Downloading Playwright Chromium...
MediaCrawler\.venv\Scripts\python.exe -m playwright install chromium
if errorlevel 1 (
  echo [x] Chromium download failed. Re-run this script to retry.
  pause
  exit /b 1
)
echo.
echo [OK] Setup complete. Double-click tools\MediaCrawler\run_xhs.cmd to collect.
pause
