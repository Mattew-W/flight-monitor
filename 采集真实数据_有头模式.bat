@echo off
chcp 65001 >nul 2>&1
set PYTHONIOENCODING=utf-8
title Flight Monitor - Real Data Collection (Headed Mode)
cd /d "%~dp0"

set PY=python
where python >nul 2>&1
if errorlevel 1 (
    if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe
)

echo ============================================
echo   Flight Monitor - Real Data Collection
echo   (Headed Mode - Manual CAPTCHA)
echo ============================================
echo.
echo   This will open a REAL mobile browser window.
echo   When CAPTCHA appears, solve it manually
echo   in the browser, then the script continues.
echo.
echo   WARNING: May take 10-30 minutes depending
echo   on number of routes.
echo.
echo ============================================
echo.

set /p limit=Enter number of routes to collect (default 3): 
if "%limit%"=="" set limit=3

set /p delay=Enter delay between searches in sec (default 3.0): 
if "%delay%"=="" set delay=3.0

echo.
echo Starting real data collection (HEADED mode)...
echo.

%PY% tools\collect_real.py -n %limit% -d %delay% --monitor --headed

echo.
echo ============================================
echo   Done! Real data saved to database.
echo ============================================
echo.
pause
