@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
echo Chzzk VOD 자동 모니터링 파이프라인 (CLI 데몬)
echo ============================================
echo.
echo 종료 방법:
echo   - Ctrl+C
echo   - output\pipeline_state.json 에서 "stop": true 로 변경
echo.
echo 트레이 모드를 원하면: pipeline_tray.bat
echo.
python -m pipeline.main
pause
