@echo off
chcp 65001 >nul 2>&1
set PYTHONIOENCODING=utf-8
title Flight Monitor - Real Data Collection
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
echo   Flight Monitor - Real Data Collection
echo   (Ctrip Browser Scraping - is_mock=0)
echo ============================================
echo.
echo   This will scrape REAL prices from Ctrip
echo   using a fresh browser per search.
echo.
echo   WARNING: May take 10-30 minutes depending
echo   on number of routes.
echo.
echo ============================================
echo.

set /p "limit=Enter number of routes to collect (default 5): "
if "%limit%"=="" set "limit=5"

set /p "delay=Enter delay between searches in sec (default 2.0): "
if "%delay%"=="" set "delay=2.0"

echo.
echo Starting real data collection ...
echo.
"%PY%" tools\collect_real.py -n %limit% -d %delay% --monitor
if errorlevel 1 (
    echo.
    echo [ERROR] collect_real.py failed.
    pause
    exit /b 1
)

echo.
echo ============================================
echo   Done! Real data saved to database.
echo ============================================
echo.
pause
exit /b 0
