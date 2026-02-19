@echo off
title Ruby Portable Setup
echo ===================================================
echo      Initializing Ruby's Portable Environment
echo ===================================================
echo.

:: Check for Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH.
    echo Please install Python 3.10+ and try again.
    pause
    exit /b
)

:: Create VENV if missing
if not exist venv (
    echo [+] Creating local virtual environment (venv)...
    python -m venv venv
) else (
    echo [+] Virtual environment exists.
)

:: Activate and Update
echo [+] Upgrading pip...
call venv\Scripts\activate
python -m pip install --upgrade pip

:: Install Dependencies
echo [+] Installing/Updating dependencies...
pip install -r requirements.txt
pip install mss Pillow anthropic google-generativeai

:: Ensure .env exists
if not exist .env (
    echo [+] Creating default configuration...
    copy .env.example .env
    echo [!] NOTE: You will need to edit .env to add your API keys!
)

:: Install Playwright Browsers
echo [+] Installing Playwright browsers...
playwright install chromium

:: Setup Desktop App
echo [+] Setting up Desktop App (Electron)...
where npm >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARNING] Node.js (npm) is not found!
    echo The desktop app requires Node.js to run.
    echo Please install generic Node.js LTS from nodejs.org
) else (
    cd desktop
    call npm install
    cd ..
)

echo.
echo ===================================================
echo             Setup Complete! 💎
echo ===================================================
echo.
echo You can now use the 'Ruby' shortcut or run 'start_memu.bat'.
echo.
pause
