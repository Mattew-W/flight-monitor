@echo off
chcp 65001 >nul 2>&1
title Flight Price Monitor
cd /d "%~dp0"

rem -- find python --
set PY=python
where python >nul 2>&1
if errorlevel 1 (
    if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe
)

:MENU
cls
echo.
echo  ============================================
echo     Flight Price Monitor
echo  ============================================
echo   [1] Start (seed + backfill + server)
echo   [2] Stop server
echo   [3] Status
echo   [4] Open browser (http://127.0.0.1:5566)
echo   [5] Reset database
echo   [0] Exit
echo  ============================================
set /p choice="> "

if "%choice%"=="1" goto START
if "%choice%"=="2" goto STOP
if "%choice%"=="3" goto STATUS
if "%choice%"=="4" goto BROWSER
if "%choice%"=="5" goto RESET
if "%choice%"=="0" goto END
goto MENU

::START
echo.
echo ============================================
echo   Launching Flight Monitor...
echo ============================================
echo.
if not exist "flight_monitor.db" (
    echo [1/3] Seeding data (56 routes, mock)...
    %PY% seed_data.py --mock-only -w 16
    if errorlevel 1 (echo Seed failed! & pause & goto MENU)
)
echo [2/3] Backfilling history for ML...
%PY% backfill_history.py
echo [3/3] Starting server...
echo Set WshShell = CreateObject("WScript.Shell") > _s.vbs
echo WshShell.Run "%PY% main.py", 0, False >> _s.vbs
cscript //nologo _s.vbs & del _s.vbs
timeout /t 3 >nul
echo Opening browser...
start "" http://127.0.0.1:5566
echo.
echo Done! Server running in background.
echo Close this window or press any key...
pause >nul
goto MENU

::STOP
echo.
echo Stopping server...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":5566" ^| findstr "LISTENING"') do (
    taskkill /PID %%a /F >nul 2>&1
    echo Process %%a killed.
)
echo Done.
pause >nul
goto MENU

::STATUS
echo.
netstat -aon | findstr ":5566" | findstr "LISTENING" >nul 2>&1
if errorlevel 1 (echo [STOPPED]) else (echo [RUNNING] http://127.0.0.1:5566)
pause >nul
goto MENU

::BROWSER
start "" http://127.0.0.1:5566
goto MENU

::RESET
echo.
set /p confirm="Delete ALL data? Type YES: "
if not "%confirm%"=="YES" goto MENU
if exist "flight_monitor.db"       del /f /q "flight_monitor.db"
if exist "flight_monitor.db-wal"   del /f /q "flight_monitor.db-wal"
if exist "flight_monitor.db-shm"   del /f /q "flight_monitor.db-shm"
echo Database cleared.
pause >nul
goto MENU

:END
echo Bye!
exit /b 0
