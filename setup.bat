@echo off
title Kaelovun — Setup and Launcher
color 07
setlocal enabledelayedexpansion
set STARTDIR=%CD%

echo ========================================
echo    Kaelovun — Setup and Launch
echo ========================================
echo.

REM ── Check Python ────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in your PATH.
    echo Install Python 3.11+ from https://python.org
    echo Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

for /f "tokens=2 delims= " %%v in ('python --version') do set PYVER=%%v
for /f "tokens=1,2 delims=." %%a in ("!PYVER!") do (
    set MAJOR=%%a
    set MINOR=%%b
)
if !MAJOR! LSS 3 (
    echo [ERROR] Python 3.11+ is required. Detected: !PYVER!
    pause
    exit /b 1
)
if !MAJOR! EQU 3 if !MINOR! LSS 11 (
    echo [ERROR] Python 3.11+ is required. Detected: !PYVER!
    pause
    exit /b 1
)
echo [OK] Python !PYVER!

REM ── Virtual environment ─────────────────────────────
if not exist ".venv" (
    echo [SETUP] Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo [OK] Virtual environment created.
) else (
    echo [OK] Virtual environment found.
)

echo [SETUP] Activating virtual environment...
call .venv\Scripts\activate.bat
if errorlevel 1 (
    echo [ERROR] Failed to activate virtual environment.
    pause
    exit /b 1
)

REM ── Dependencies ────────────────────────────────────
if not exist requirements.txt (
    echo [ERROR] requirements.txt not found.
    pause
    exit /b 1
)

echo [SETUP] Installing dependencies...
python -m pip install --upgrade pip >nul 2>&1
pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Failed to install some dependencies.
    pause
    exit /b 1
)
echo [OK] All dependencies installed.

REM ── Launch ──────────────────────────────────────────
echo.
echo ========================================
echo    Starting Kaelovun
echo ========================================
echo.
python main.py

echo.
echo Kaelovun has exited.
echo Run this file again to launch the app.
pause >nul

cd /d "%STARTDIR%"
endlocal
