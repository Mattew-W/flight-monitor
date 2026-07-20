@echo off
chcp 65001 >nul 2>&1
set PYTHONIOENCODING=utf-8
title Flight Monitor - Real Data Collection (Headed)
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

set /p "limit=Enter number of routes to collect (default 3): "
if "%limit%"=="" set "limit=3"

set /p "delay=Enter delay between searches in sec (default 3.0): "
if "%delay%"=="" set "delay=3.0"

echo.
echo Starting real data collection (HEADED mode) ...
echo.
"%PY%" tools\collect_real.py -n %limit% -d %delay% --monitor --headed
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
