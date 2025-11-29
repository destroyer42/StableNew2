@echo off
REM ===============================================
REM  StableNew - Last Change Diff Helper
REM -----------------------------------------------
REM  Writes the diff of the most recent commit
REM  into tools\last_change.diff
REM
REM  Usage (from repo root, in cmd):
REM      tools\make_patch.cmd
REM ===============================================

setlocal

REM Ensure we are in the repo root (script may be called from elsewhere)
cd /d "%~dp0.."

if not exist ".git" (
    echo ERROR: .git directory not found. Run this from inside the StableNew repo.
    exit /b 1
)

echo === Generating last_change.diff for HEAD~1... ===
git diff HEAD~1 > tools\last_change.diff

if errorlevel 1 (
    echo ERROR: git diff failed.
    exit /b 1
)

echo.
echo ✅ Diff written to tools\last_change.diff
echo    You can upload this file alongside your snapshot ZIP to ChatGPT.
echo.

endlocal
exit /b 0
