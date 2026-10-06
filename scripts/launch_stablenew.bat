@echo off
REM StableNew canonical Windows launcher (PR-DEVEX-LAUNCH-180).
REM Delegates to launch_stablenew.ps1, which resolves this checkout, reuses or creates the repository .venv and
REM starts StableNew with that .venv's Python. Arguments are forwarded; the application's exit code is returned.
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch_stablenew.ps1" %*
set "STABLENEW_EXIT=%ERRORLEVEL%"
if "%STABLENEW_EXIT%"=="0" exit /b 0
REM Keep the window readable when this file was double-clicked and the launch failed.
set "STABLENEW_CMDLINE=%CMDCMDLINE:"=%"
if /i not "%STABLENEW_CMDLINE:launch_stablenew=%"=="%STABLENEW_CMDLINE%" pause
exit /b %STABLENEW_EXIT%
