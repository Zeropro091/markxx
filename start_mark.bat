@echo off
title START MARK-ONLY
setlocal enabledelayedexpansion

echo.
echo  ==========================================
echo   STARTING MARK-XX ASISTANT
echo  ==========================================
echo.

:: 1. Cek MARK-XX UI (main.py)
wmic process where "name='python.exe'" get commandline | findstr /i "main.py" >nul
if %errorlevel% equ 0 (
    echo  [OK] MARK-XX UI is already running.
) else (
    echo  [!] MARK-XX UI is offline. Launching...
    if exist "venv\Scripts\python.exe" (
        start "" venv\Scripts\python.exe main.py
        echo  [*] MARK-XX UI started.
    ) else (
        echo  [ERROR] venv not found. Run setup.bat first.
    )
)

:: 2. Cek MARK-XX CLI (markcli.py)
wmic process where "name='python.exe'" get commandline | findstr /i "markcli.py" >nul
if %errorlevel% equ 0 (
    echo  [OK] MARK-XX CLI is already running.
) else (
    echo  [!] MARK-XX CLI is offline. Launching...
    if exist "venv\Scripts\python.exe" (
        start "MARK-XX CLI" venv\Scripts\python.exe markcli.py
        echo  [*] MARK-XX CLI started in new window.
    )
)

echo.
echo  ==========================================
echo   Done! MARK-XX is ready.
echo  ==========================================
echo.
timeout /t 3
