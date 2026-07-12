@echo off
chcp 65001 >nul 2>&1
title Flight Price Monitor

:MENU
cls
echo.
echo  ============================================
echo            Flight Price Monitor
echo  ============================================
echo.
echo   [1] Start Server    (Launch web UI)
echo   [2] Stop Server     (Kill process)
echo   [3] Check Status    (Is it running?)
echo   [4] Open Browser    (http://127.0.0.1:5566)
echo   [5] Install Dependencies
echo   [6] Reset Database  (Delete all data)
echo   [0] Exit
echo.
set /p choice="Enter choice: "

if "%choice%"=="1" goto START
if "%choice%"=="2" goto STOP
if "%choice%"=="3" goto STATUS
if "%choice%"=="4" goto BROWSER
if "%choice%"=="5" goto INSTALL
if "%choice%"=="6" goto RESET
if "%choice%"=="0" goto END
goto MENU

:START
echo.
echo  Starting Flight Monitor...
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo  Creating virtual environment...
    python -m venv .venv
)
if not exist ".venv\Scripts\flask.exe" (
    echo  Installing dependencies...
    .venv\Scripts\pip install flask requests >nul 2>&1
)
echo  Launching server at http://127.0.0.1:5566 ...
start "" .venv\Scripts\python.exe main.py
timeout /t 3 >nul
echo.
echo  Server started! Opening browser...
start "" http://127.0.0.1:5566
echo.
pause
goto MENU

:STOP
echo.
echo  Stopping Flight Monitor...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":5566" ^| findstr "LISTENING"') do (
    taskkill /PID %%a /F >nul 2>&1
    echo  Process PID %%a terminated.
)
taskkill /fi "WINDOWTITLE eq Flight Price Monitor*" /f >nul 2>&1
echo  Done.
echo.
pause
goto MENU

:STATUS
echo.
netstat -aon | findstr ":5566" | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo  [RUNNING] Server is online at http://127.0.0.1:5566
) else (
    echo  [STOPPED] Server is not running.
)
echo.
pause
goto MENU

:BROWSER
echo.
echo  Opening browser...
start "" http://127.0.0.1:5566
timeout /t 1 >nul
goto MENU

:INSTALL
echo.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo  Creating virtual environment...
    python -m venv .venv
)
echo  Installing dependencies...
.venv\Scripts\pip install flask requests
echo.
echo  Done!
pause
goto MENU

:RESET
echo.
set /p confirm="  WARNING: This will delete ALL data. Type YES to confirm: "
if not "%confirm%"=="YES" (
    echo  Cancelled.
    pause
    goto MENU
)
cd /d "%~dp0"
if exist "flight_monitor.db" del /f /q "flight_monitor.db"
if exist "flight_monitor.db-wal" del /f /q "flight_monitor.db-wal"
if exist "flight_monitor.db-shm" del /f /q "flight_monitor.db-shm"
echo  Database deleted. All data cleared.
echo.
pause
goto MENU

:END
echo  Bye!
exit /b 0
