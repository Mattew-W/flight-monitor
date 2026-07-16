@echo off
chcp 65001 >nul 2>&1
title Flight Monitor - Real Data Collection
cd /d "%~dp0"

set PY=python
where python >nul 2>&1
if errorlevel 1 (
    if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe
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

set /p limit=Enter number of routes to collect (default 5): 
if "%limit%"=="" set limit=5

set /p delay=Enter delay between searches in sec (default 2.0): 
if "%delay%"=="" set delay=2.0

echo.
echo Starting real data collection...
echo.

%PY% tools\collect_real.py -n %limit% -d %delay% --monitor

echo.
echo ============================================
echo   Done! Real data saved to database.
echo ============================================
echo.
pause
