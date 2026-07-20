@echo off
chcp 65001 >nul 2>&1
set PYTHONIOENCODING=utf-8
title Flight Monitor Server Starter
cd /d "%~dp0"

:: ---- Resolve Python interpreter ----
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (
    set "PY=python"
    where python >nul 2>&1 || (
        echo [FATAL] Python not found!
        pause
        exit /b 1
    )
)

echo ============================================
echo   Flight Monitor - Starting Server
echo ============================================
echo.
echo   http://127.0.0.1:5566
echo ============================================
echo.

:: ---- Kill any existing server ----
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr /r /c:":5566 .*[Ll][Ii][Ss][Tt][Ee][Nn]"') do (
    echo Stopping old server [PID: %%a]...
    taskkill /PID %%a /F >nul 2>&1
)

:: ---- Launch server in a new window ----
start "Flight Monitor Server" "%PY%" main.py

echo Waiting for server to start...
timeout /t 5 /nobreak >nul 2>&1

netstat -ano 2>nul | findstr /r /c:":5566 .*[Ll][Ii][Ss][Tt][Ee][Nn]" >nul 2>&1
if errorlevel 1 (
    echo.
    echo [WARN] Server may not have started. Check the server window.
) else (
    echo.
    echo [OK] Server running at http://127.0.0.1:5566
)

:: ---- Open browser ----
start "" http://127.0.0.1:5566

echo.
echo Close this window to stop the server launcher.
echo (The server runs in its own window.)
echo.
echo To stop server, close the server window, or use
echo   flight_monitor_console.bat ^> option [5]
echo.
pause >nul

:: ---- Cleanup on exit ----
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr /r /c:":5566 .*[Ll][Ii][Ss][Tt][Ee][Nn]"') do (
    taskkill /PID %%a /F >nul 2>&1
)

exit /b 0
