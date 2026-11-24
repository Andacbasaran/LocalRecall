@echo off
chcp 65001 >nul
title LocalRecall — 100%% Offline Smart Screen Memory
cd /d "%~dp0.."

if exist "%~dp0..\dist\LocalRecall\LocalRecall.exe" (
    start "" "%~dp0..\dist\LocalRecall\LocalRecall.exe" %*
    exit /b 0
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/2] Creating virtual environment .venv...
    python -m venv .venv
    if %ERRORLEVEL% NEQ 0 (
        echo [ERROR] Python 3.10+ is required on PATH.
        pause
        exit /b 1
    )
)

if not exist ".venv\.deps_installed" (
    echo [2/2] Installing dependencies...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install --prefer-binary -r requirements.txt
    if %ERRORLEVEL% NEQ 0 (
        echo [ERROR] Dependency installation failed.
        pause
        exit /b 1
    )
    type nul > ".venv\.deps_installed"
)

start "" ".venv\Scripts\pythonw.exe" main.py %*
