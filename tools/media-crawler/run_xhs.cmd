@echo off
rem MediaCrawler XHS search run, pinned to workspace-local browser/temp paths.
rem This machine denies subprocess writes under the user profile (AppData\Local),
rem so the Playwright browsers, matplotlib cache and temp dirs live inside tools/MediaCrawler.
rem Usage: run_xhs.cmd  (first run: scan the QR code with the secondary account)
setlocal
cd /d %~dp0
set PLAYWRIGHT_BROWSERS_PATH=%~dp0.pw-browsers
set MPLCONFIGDIR=%~dp0.mplcache
set TMP=%~dp0.tmp
set TEMP=%~dp0.tmp
.venv\Scripts\python.exe main.py --platform xhs --lt qrcode --type search
rem Keep the console open so the outcome (or the error) stays visible on double-click.
pause
endlocal
