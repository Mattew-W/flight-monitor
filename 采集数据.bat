@echo off
chcp 65001 >nul 2>&1
set PYTHONIOENCODING=utf-8
title Flight Monitor - Mock Data Collection
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
echo   Flight Monitor - Mock Data Collection
echo ============================================
echo.
echo   This script does two things:
echo   1. Generate mock flight price data
echo   2. Backfill historical prices (past 30 days)
echo.
echo   Press Ctrl+C to cancel.
echo ============================================
echo.

echo [1/2] Generating mock flight price data ...
echo.
"%PY%" tools\seed_data.py --mock-only -w 16
if errorlevel 1 (
    echo.
    echo [ERROR] Mock data generation failed!
    pause
    exit /b 1
)
echo.
echo [OK] Mock data generated.
echo.

echo [2/2] Backfilling historical price records ...
echo.
"%PY%" tools\backfill_history.py
if errorlevel 1 (
    echo.
    echo [ERROR] Historical backfill failed!
    pause
    exit /b 1
)
echo.
echo [OK] Historical backfill complete.
echo.
echo ============================================
echo   All done! Start the server to view data.
echo ============================================
echo.
pause
exit /b 0
