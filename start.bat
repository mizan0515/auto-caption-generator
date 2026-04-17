@echo off
REM ASCII-only launcher. Korean UI is printed by first_run.py under UTF-8 stdio.
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo Chzzk VOD Pipeline - one-click launcher
echo ---------------------------------------
python scripts\first_run.py %*
set RC=%ERRORLEVEL%
if %RC% neq 0 (
    echo.
    echo [ABORT] pre-flight failed ^(exit=%RC%^). See messages above.
    pause
    exit /b %RC%
)
echo.
echo Done. Tray icon may be hidden under the '^^' overflow on the taskbar.
echo A dashboard window has been opened so you can see it working.
echo This window will close in 5 seconds - you can close it now.
timeout /t 5 >nul
