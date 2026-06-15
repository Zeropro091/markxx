@echo off
rem Restart script for MARK-XX
echo Restarting MARK-XX...
call venv\Scripts\activate.bat
python main.py
pause
