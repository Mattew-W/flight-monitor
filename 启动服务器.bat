@echo off
chcp 65001 >nul 2>&1
title Flight Monitor
cd /d "%~dp0"

set PY=python
where python >nul 2>&1
if errorlevel 1 (
    if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe
)

echo ============================================
echo   Flight Monitor - Starting...
echo ============================================
echo.
echo   http://127.0.0.1:5566
echo ============================================
echo.

rem -- Start server in background --
echo Set WshShell = CreateObject("WScript.Shell") > _s.vbs
echo WshShell.Run "%PY% main.py", 0, False >> _s.vbs
cscript //nologo _s.vbs & del _s.vbs

rem -- Wait for server to start --
timeout /t 3 >nul

rem -- Open browser --
start "" http://127.0.0.1:5566

echo Done! Server running in background.
echo Close this window or press any key...
pause >nul
