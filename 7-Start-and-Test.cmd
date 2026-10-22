@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-SITL.ps1" -TestAfterStart
set "sitl_exit=%errorlevel%"
pause
exit /b %sitl_exit%
