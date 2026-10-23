@echo off
rem Right-click this file and choose "以管理员身份运行", or just double-click and approve UAC.
rem It exists because a non-elevated process cannot raise the consent prompt for itself.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-docker.ps1"
pause
