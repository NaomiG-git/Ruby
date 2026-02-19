@echo off
setlocal
title Ruby Packager

set "SOURCE_DIR=%~dp0"
set "DEST_DIR=%USERPROFILE%\Desktop\Ruby_Installer_For_Marc"

echo ===================================================
echo      Packaging Ruby for Transfer 📦
echo ===================================================
echo.
echo Source: %SOURCE_DIR%
echo Dest:   %DEST_DIR%
echo.

if exist "%DEST_DIR%" (
    echo [!] Destination exists. Cleaning up...
    rmdir /s /q "%DEST_DIR%"
)
mkdir "%DEST_DIR%"

echo [+] Copying core files...
xcopy "%SOURCE_DIR%*.py" "%DEST_DIR%\" /Y /Q
xcopy "%SOURCE_DIR%*.bat" "%DEST_DIR%\" /Y /Q
xcopy "%SOURCE_DIR%*.vbs" "%DEST_DIR%\" /Y /Q
xcopy "%SOURCE_DIR%*.md" "%DEST_DIR%\" /Y /Q
xcopy "%SOURCE_DIR%*.txt" "%DEST_DIR%\" /Y /Q
xcopy "%SOURCE_DIR%*.ico" "%DEST_DIR%\" /Y /Q
xcopy "%SOURCE_DIR%*.ps1" "%DEST_DIR%\" /Y /Q
xcopy "%SOURCE_DIR%.env" "%DEST_DIR%\" /Y /Q
xcopy "%SOURCE_DIR%.env.example" "%DEST_DIR%\" /Y /Q
xcopy "%SOURCE_DIR%kill_ruby.bat" "%DEST_DIR%\" /Y /Q

echo [+] Copying Source Code (src)...
xcopy "%SOURCE_DIR%src" "%DEST_DIR%\src" /I /E /Y /Q

echo [+] Copying Config...
xcopy "%SOURCE_DIR%config" "%DEST_DIR%\config" /I /E /Y /Q

echo [+] Copying UI...
xcopy "%SOURCE_DIR%ui" "%DEST_DIR%\ui" /I /E /Y /Q

echo [+] Copying Desktop App (Clean)...
mkdir "%DEST_DIR%\desktop"
xcopy "%SOURCE_DIR%desktop\*.js" "%DEST_DIR%\desktop\" /Y /Q
xcopy "%SOURCE_DIR%desktop\*.json" "%DEST_DIR%\desktop\" /Y /Q
xcopy "%SOURCE_DIR%desktop\*.css" "%DEST_DIR%\desktop\" /Y /Q
xcopy "%SOURCE_DIR%desktop\*.html" "%DEST_DIR%\desktop\" /Y /Q

echo.
echo ===================================================
echo      Packaging Complete! 🎁
echo ===================================================
echo.
echo 1. Copy the folder "Ruby_Installer_For_Marc" from your Desktop to a USB drive or shared folder.
echo 2. On Marc's computer:
echo    a. Install Python 3.10+ (python.org)
echo    b. Install Node.js LTS (nodejs.org)
echo    c. Open the folder and run 'portable_setup.bat'
echo    d. Run 'create_shortcut.ps1' (Right click -> Run with PowerShell)
echo.
pause
