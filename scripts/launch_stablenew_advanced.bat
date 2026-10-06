@echo off
REM Retired (PR-DEVEX-LAUNCH-180): there is one launcher, launch_stablenew.bat. This file only forwards to it so an
REM old shortcut cannot start StableNew with whatever python happens to be on PATH.
call "%~dp0launch_stablenew.bat" %*
exit /b %ERRORLEVEL%
