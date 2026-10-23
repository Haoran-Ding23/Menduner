@echo off
rem Double-click this file. It runs the PowerShell installer, which re-launches itself elevated
rem so you only have to approve one UAC prompt.
rem ASCII only: cmd.exe renders .cmd files in the OEM code page, and non-ASCII text in a launcher
rem is never worth the risk.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-docker.ps1"
pause
