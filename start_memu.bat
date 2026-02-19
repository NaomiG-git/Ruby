@echo off
title MemU Agent
echo Starting MemU Agent...
cd /d "%~dp0"

:: Wait a moment for server to potentially start or just open browser
:: Start the Electron App (which starts the Python backend)
:: First, ensure backend runs in correct env if launched via Electron
if exist venv\Scripts\activate.bat call venv\Scripts\activate.bat

cd desktop
call npm start

pause
