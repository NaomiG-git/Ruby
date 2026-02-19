@echo off
echo Killing Ruby Assistant processes...
taskkill /F /IM "Ruby Assistant.exe" /T >nul 2>&1
taskkill /F /IM electron.exe /T >nul 2>&1
taskkill /F /IM python.exe /T >nul 2>&1
taskkill /F /IM node.exe /T >nul 2>&1
echo Done. Please try starting Ruby again.
pause
