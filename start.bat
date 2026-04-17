@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo Chzzk VOD 파이프라인 — 원클릭 런처
echo -------------------------------------
python scripts\first_run.py %*
set RC=%ERRORLEVEL%
if %RC% neq 0 (
    echo.
    echo [중단] 점검 실패 ^(exit=%RC%^). 위 메시지를 확인하세요.
    pause
    exit /b %RC%
)
echo.
echo 완료 — 트레이 아이콘을 확인하세요.
timeout /t 3 >nul
