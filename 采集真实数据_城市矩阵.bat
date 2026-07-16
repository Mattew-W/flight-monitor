@echo off
chcp 65001 >nul 2>&1
set PYTHONIOENCODING=utf-8
title Flight Monitor - City Matrix Mode
cd /d "%~dp0"

set PY=python
where python >nul 2>&1
if errorlevel 1 (
    if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe
)

echo ============================================
echo   Flight Monitor - City Matrix Collection
echo   (20 Cities x 19 = 380 Routes)
echo ============================================
echo.
echo   This will scrape ALL combinations of
echo   20 core cities (380 routes).
echo.
echo   Estimated: 2-4 hours with CAPTCHA solving
echo.
echo ============================================
echo.

set /p mode=Select mode: [1]Headed(auto-CAPTCHA) [2]Headless: 
if "%mode%"=="" set mode=1

set /p delay=Enter delay between searches in sec (default 3.0): 
if "%delay%"=="" set delay=3.0

echo.
echo Starting city matrix collection...
echo.

if "%mode%" equ "1" (
    %PY% tools\collect_real.py --full-matrix -d %delay% --monitor --headed
) else (
    %PY% tools\collect_real.py --full-matrix -d %delay% --monitor
)

echo.
echo ============================================
echo   Done!
echo ============================================
echo.
pause
