@echo off
chcp 65001 >nul 2>&1
set PYTHONIOENCODING=utf-8
title Flight Monitor Console
cd /d "%~dp0"

:: ---- Resolve Python interpreter ----
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (
    set "PY=python"
    where python >nul 2>&1 || (
        echo [FATAL] Python not found. Please install Python 3.10+ first.
        pause
        exit /b 1
    )
)

:MENU
cls
echo.
echo   ============================================
echo        F L I G H T   M O N I T O R
echo   ============================================
echo.
echo     1. Start Server       (port 5566)
echo     2. Collect MOCK Data  (fast, for testing)
echo     3. Collect REAL Data  (Ctrip headless)
echo     4. Collect REAL Data  (Headed ^| CAPTCHA)
echo     5. Stop Server
echo     6. Check Status
echo.
echo     0. Exit
echo.
echo   ============================================

choice /c 1234560 /n /m "   Select [0-6]: "
if errorlevel 7 goto :EXIT
if errorlevel 6 goto :STATUS
if errorlevel 5 goto :STOP
if errorlevel 4 goto :HEADEDCOLLECT
if errorlevel 3 goto :REALCOLLECT
if errorlevel 2 goto :COLLECT
if errorlevel 1 goto :START
goto :MENU

:START
echo.
echo   Starting server...
echo.
:: Kill any existing listener on :5566
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr /r /c:":5566 .*[Ll][Ii][Ss][Tt][Ee][Nn]"') do (
    echo   ^| old server PID=%%a, killing...
    taskkill /PID %%a /F >nul 2>&1
)
cd /d "%~dp0"
start "" "%PY%" main.py
echo.
echo   Waiting for server to start ...
timeout /t 5 /nobreak >nul 2>&1
netstat -ano 2>nul | findstr /r /c:":5566 .*[Ll][Ii][Ss][Tt][Ee][Nn]" >nul 2>&1
if errorlevel 1 (
    echo   [WARN] Server may not have started. Check the server window.
) else (
    echo   [OK] Server running at http://127.0.0.1:5566
    echo.
    echo   Opening browser ...
    start "" http://127.0.0.1:5566
)
echo.
echo   Use [5] to stop the server.
echo.
pause
goto :MENU

:COLLECT
echo.
echo   Collecting MOCK data ...
echo.
"%PY%" tools\seed_data.py --mock-only -w 16
if errorlevel 1 (
    echo.
    echo   [ERROR] seed_data.py failed ^(exit code !errorlevel!^)
    pause
    goto :MENU
)
echo.
"%PY%" tools\backfill_history.py
if errorlevel 1 (
    echo.
    echo   [ERROR] backfill_history.py failed
    pause
    goto :MENU
)
echo.
echo   [DONE] Mock data ready.
pause
goto :MENU

:REALCOLLECT
echo.
echo   Collecting REAL data from Ctrip ...
echo.
"%PY%" tools\collect_real.py -n 5 -d 2.0 --monitor
if errorlevel 1 (
    echo.
    echo   [ERROR] collect_real.py failed
    pause
    goto :MENU
)
echo.
echo   [DONE] Real data saved.
pause
goto :MENU

:HEADEDCOLLECT
echo.
echo   Collecting REAL data (Headed Mode - CAPTCHA) ...
echo.
"%PY%" tools\collect_real.py -n 3 -d 3.0 --monitor --headed
if errorlevel 1 (
    echo.
    echo   [ERROR] collect_real.py failed
    pause
    goto :MENU
)
echo.
echo   [DONE] Real data saved.
pause
goto :MENU

:STOP
echo.
echo   Stopping server ...
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr /r /c:":5566 .*[Ll][Ii][Ss][Tt][Ee][Nn]"') do (
    echo   ^| killing PID=%%a
    taskkill /PID %%a /F >nul 2>&1
)
echo.
echo   [DONE]
pause
goto :MENU

:STATUS
echo.
echo   Status:
echo.
netstat -ano 2>nul | findstr /r /c:":5566 .*[Ll][Ii][Ss][Tt][Ee][Nn]" >nul 2>&1
if errorlevel 1 (
    echo     Server  : NOT RUNNING
) else (
    echo     Server  : RUNNING
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr /r /c:":5566 .*[Ll][Ii][Ss][Tt][Ee][Nn]"') do (
        echo     PID   : %%a
    )
)
echo.
echo   Python processes:
tasklist 2>nul | find /i "python" | find /v "find"
echo.
pause
goto :MENU

:EXIT
echo.
echo   Bye!
timeout /t 1 /nobreak >nul 2>&1
exit /b 0
