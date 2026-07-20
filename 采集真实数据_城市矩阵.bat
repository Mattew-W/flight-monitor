@echo off
chcp 65001 >nul 2>&1
set PYTHONIOENCODING=utf-8
title Flight Monitor - City Matrix Mode
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

choice /c 12 /n /m "Select mode: [1]Headed(auto-CAPTCHA) [2]Headless: "
set "MODE=%errorlevel%"

set /p "delay=Enter delay between searches in sec (default 3.0): "
if "%delay%"=="" set "delay=3.0"

echo.
echo Starting city matrix collection ...
echo.

if "%MODE%"=="1" (
    "%PY%" tools\collect_real.py --full-matrix -d %delay% --monitor --headed
) else (
    "%PY%" tools\collect_real.py --full-matrix -d %delay% --monitor
)
if errorlevel 1 (
    echo.
    echo [ERROR] collect_real.py failed.
    pause
    exit /b 1
)

echo.
echo ============================================
echo   Done!
echo ============================================
echo.
pause
exit /b 0
