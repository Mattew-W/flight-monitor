@echo off
chcp 65001 >nul 2>&1
title Flight Monitor - Collect
cd /d "%~dp0"

set PY=python
where python >nul 2>&1
if errorlevel 1 (
    if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe
)

echo ============================================
echo   Flight Monitor - Collect Data
echo ============================================
echo.

%PY% tools\seed_data.py --mock-only -w 16
echo.
%PY% tools\backfill_history.py
echo.
echo ============================================
echo   Done!
echo ============================================
pause
