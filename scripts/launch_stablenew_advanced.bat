@echo off
REM Advanced StableNew GUI Launcher
REM This batch file automatically finds the StableNew installation and launches it

setlocal enabledelayedexpansion

echo.
echo ===============================================
echo   StableNew - Stable Diffusion Automation
echo ===============================================
echo.

REM Try to find StableNew installation
set "STABLENEW_PATH="

REM Check current directory first
if exist "%~dp0src\main.py" (
    set "STABLENEW_PATH=%~dp0"
    goto :found
)

REM Check common installation locations
for %%d in (
    "C:\Users\%USERNAME%\projects\StableNew"
    "C:\StableNew"
    "D:\StableNew"
    "%USERPROFILE%\StableNew"
    "%USERPROFILE%\Documents\StableNew"
) do (
    if exist "%%d\src\main.py" (
        set "STABLENEW_PATH=%%d"
        goto :found
    )
)

echo ❌ Error: Could not find StableNew installation
echo Please make sure StableNew is installed in one of these locations:
echo   - %~dp0
echo   - C:\Users\%USERNAME%\projects\StableNew
echo   - C:\StableNew
echo   - %USERPROFILE%\StableNew
echo.
pause
exit /b 1

:found
echo 📍 Found StableNew at: !STABLENEW_PATH!
echo 🔄 Changing to StableNew directory...
cd /d "!STABLENEW_PATH!"

echo 🐍 Checking Python installation...
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Error: Python not found in PATH
    echo Please install Python or add it to your PATH
    pause
    exit /b 1
)

echo ✅ Python found
echo 🚀 Starting StableNew GUI...
echo.

python -m src.main

echo.
echo 👋 StableNew has closed
pause
