@echo off
title MARK-XX Setup
echo.
echo  ███╗   ███╗ █████╗ ██████╗ ██╗  ██╗    ██╗  ██╗██╗  ██╗
echo  ████╗ ████║██╔══██╗██╔══██╗██║ ██╔╝    ╚██╗██╔╝╚██╗██╔╝
echo  ██╔████╔██║███████║██████╔╝█████╔╝      ╚███╔╝  ╚███╔╝
echo  ██║╚██╔╝██║██╔══██║██╔══██╗██╔═██╗      ██╔██╗  ██╔██╗
echo  ██║ ╚═╝ ██║██║  ██║██║  ██║██║  ██╗    ██╔╝ ██╗██╔╝ ██╗
echo  ╚═╝     ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝    ╚═╝  ╚═╝╚═╝  ╚═╝
echo.
echo  Personal AI Assistant - Setup Script
echo  ======================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not on PATH.
    echo Please install Python 3.10+ from https://python.org
    pause
    exit /b 1
)
echo [OK] Python found.

:: Create virtual environment
if not exist "venv" (
    echo [*] Creating virtual environment...
    python -m venv venv
)
echo [OK] Virtual environment ready.

:: Activate venv
call venv\Scripts\activate.bat

:: Upgrade pip
echo [*] Upgrading pip...
python -m pip install --upgrade pip --quiet

:: Install core packages
echo [*] Installing packages (this may take a few minutes)...
pip install PyQt6 --quiet
pip install google-generativeai --quiet
pip install faster-whisper --quiet
pip install edge-tts --quiet
pip install pyttsx3 --quiet
pip install sounddevice --quiet
pip install numpy --quiet
pip install mss --quiet
pip install opencv-python --quiet
pip install Pillow --quiet
pip install pyautogui --quiet
pip install PyMuPDF --quiet
pip install scipy --quiet

echo.
echo [OK] All packages installed!
echo.

:: Create required directories
if not exist "memory" mkdir memory
if not exist "config" mkdir config

echo [OK] Directories created.
echo.
echo  ============================================
echo   MARK-XX is ready to launch!
echo   Run:  venv\Scripts\python.exe main.py
echo   Or double-click: run.bat
echo  ============================================
echo.

:: Create run.bat for convenience
echo @echo off > run.bat
echo call venv\Scripts\activate.bat >> run.bat
echo python main.py >> run.bat

echo [*] Created run.bat for easy launching.
echo.
pause
