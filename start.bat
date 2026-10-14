@echo off
setlocal DisableDelayedExpansion
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows-dev.ps1" -Action Start
set "MENDUNER_RESULT=%ERRORLEVEL%"
echo.
if not "%MENDUNER_RESULT%"=="0" echo Menduner 启动失败。请阅读上面的提示信息。
pause
exit /b %MENDUNER_RESULT%
