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
echo Done - check the tray icon.
timeout /t 3 >nul
