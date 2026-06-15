@echo off
title MARK-XX System Starter
setlocal enabledelayedexpansion

echo.
echo  ==========================================
echo   MARK-XX SYSTEM CHECK
echo  ==========================================
echo.

:: 1. Cek Note Taking App (Port 3000)
:: Mengecek apakah ada proses yang mendengarkan di port 3000
netstat -ano | findstr LISTENING | findstr :3000 >nul
if %errorlevel% equ 0 (
    echo  [OK] Note Taking App is already active (Listening on 3000).
) else (
    echo  [!] Note Taking App is offline. Starting...
    if exist "C:\Users\Putu Ari\note-taking-app" (
        pushd "C:\Users\Putu Ari\note-taking-app"
        start /min cmd /c "npm run dev"
        popd
        echo  [*] Note Taking App launched in background.
    ) else (
        echo  [ERROR] C:\Users\Putu Ari\note-taking-app NOT FOUND.
    )
)

:: 2. Cek MARK-XX UI (main.py)
:: Kita gunakan WMIC untuk mengecek baris perintah (command line) dari python
wmic process where "name='python.exe'" get commandline | findstr /i "main.py" >nul
if %errorlevel% equ 0 (
    echo  [OK] MARK-XX UI (main.py) is already running.
) else (
    echo  [!] MARK-XX UI is offline. Launching...
    if exist "venv\Scripts\python.exe" (
        start "" venv\Scripts\python.exe main.py
        echo  [*] MARK-XX UI started.
    ) else (
        echo  [ERROR] venv not found. Run setup.bat.
    )
)

:: 3. Cek MARK-XX CLI (markcli.py)
wmic process where "name='python.exe'" get commandline | findstr /i "markcli.py" >nul
if %errorlevel% equ 0 (
    echo  [OK] MARK-XX CLI (markcli.py) is already running.
) else (
    echo  [!] MARK-XX CLI is offline. Launching...
    if exist "venv\Scripts\python.exe" (
        start "MARK-XX CLI" venv\Scripts\python.exe markcli.py
        echo  [*] MARK-XX CLI started in new window.
    )
)

echo.
echo  ==========================================
echo   Done! Press any key to exit this loader.
echo  ==========================================
echo.
pause
