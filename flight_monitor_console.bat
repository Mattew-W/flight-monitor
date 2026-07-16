@echo off
cd /d "%~dp0"

set PY=python
where python 2>nul
if errorlevel 1 (
    if exist ".venv\Scripts\python.exe" (
        set PY=.venv\Scripts\python.exe
    )
)

::MENU
cls
echo.
echo  ============================================
echo     FLIGHT MONITOR CONSOLE
echo  ============================================
echo   1. Start Server + Open Browser
echo   2. Collect Mock Data
echo   3. Collect Real Data (Ctrip)
echo   4. Collect Real Data (Headed/CAPTCHA)
echo   5. Stop All Services
echo   6. Check Status
echo   0. Exit
echo  ============================================
echo.
set choice=
set /p choice=Select [0-6]: 

if "%choice%" equ "1" goto START
if "%choice%" equ "2" goto COLLECT
if "%choice%" equ "3" goto REALCOLLECT
if "%choice%" equ "4" goto HEADEDCOLLECT
if "%choice%" equ "5" goto STOP
if "%choice%" equ "6" goto STATUS
if "%choice%" equ "0" goto EXIT
echo Invalid option
pause
goto MENU

::START
echo.
echo Starting server in background...
echo.
start /b "" %PY% main.py

echo Waiting for server to start...
ping -n 5 127.0.0.1 >nul

start http://127.0.0.1:5566
echo.
echo ============================================
echo   Server running on http://127.0.0.1:5566
echo   Use [5] to stop all services
echo ============================================
echo.
pause
goto MENU

::COLLECT
echo.
echo Collecting MOCK data...
echo.
%PY% tools\seed_data.py --mock-only -w 16
%PY% tools\backfill_history.py
echo.
echo Done.
pause
goto MENU

::REALCOLLECT
echo.
echo Collecting REAL data from Ctrip...
echo.
%PY% tools\collect_real.py -n 5 -d 2.0 --monitor
echo.
echo Done.
pause
goto MENU

::HEADEDCOLLECT
echo.
echo Collecting REAL data (Headed Mode - Manual CAPTCHA)...
echo.
echo A browser window will open. Solve CAPTCHA when it appears.
echo.
%PY% tools\collect_real.py -n 3 -d 3.0 --monitor --headed
echo.
echo Done.
pause
goto MENU

::STOP
echo.
echo Stopping all services...
echo.
taskkill /f /im python.exe 2>nul
taskkill /f /im chrome.exe 2>nul
taskkill /f /im chromedriver.exe 2>nul
echo.
echo Done.
pause
goto MENU

::STATUS
echo.
echo Status:
echo.
netstat -ano 2>nul | find ":5566"
tasklist 2>nul | find /i "python" | find /v "find"
echo.
pause
goto MENU

::EXIT
echo Bye.
exit /b 0
