@echo off
REM ASCII-only launcher. Korean UI is printed by first_run.py under UTF-8 stdio.
REM Prefers python.org / winget Python (NOT Microsoft Store sandboxed Python)
REM because the MS Store Python App Container blocks Shell_NotifyIcon from
REM actually rendering the tray icon.
chcp 65001 >nul
cd /d "%~dp0"

set "PY_EXE="
REM 1) winget / python.org per-user install (most common)
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    set "PY_EXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
)
REM 2) python.org all-users install
if not defined PY_EXE if exist "%ProgramFiles%\Python312\python.exe" (
    set "PY_EXE=%ProgramFiles%\Python312\python.exe"
)
REM 3) py launcher (python.org installer registers this)
if not defined PY_EXE where py.exe >nul 2>nul (
    set "PY_EXE=py.exe -3.12"
)
REM 4) fallback to whatever "python" resolves to (may be MS Store - tray icon won't show)
if not defined PY_EXE (
    set "PY_EXE=python"
)

echo.
echo Chzzk VOD Pipeline - one-click launcher
echo ---------------------------------------
echo Using Python: %PY_EXE%
echo.
%PY_EXE% scripts\first_run.py %*
set RC=%ERRORLEVEL%
if %RC% neq 0 (
    echo.
    echo [ABORT] pre-flight failed ^(exit=%RC%^). See messages above.
    pause
    exit /b %RC%
)
echo.
echo Done. A dashboard window has opened - all controls live there.
echo The tray icon (if visible) is under the '^^' overflow on the taskbar.
echo This window will close in 5 seconds - you can close it now.
timeout /t 5 >nul
