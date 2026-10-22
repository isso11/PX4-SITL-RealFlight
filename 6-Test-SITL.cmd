@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Test-SITL.ps1"
set "sitl_exit=%errorlevel%"
pause
exit /b %sitl_exit%
