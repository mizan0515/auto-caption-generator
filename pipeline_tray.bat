@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
echo Chzzk VOD 파이프라인 트레이 앱을 시작합니다...
start /B pythonw "%~dp0tray_app.py"
echo.
echo 시스템 트레이에 아이콘이 나타납니다.
echo 우클릭으로 상태 확인, 설정, 일시정지, 종료가 가능합니다.
timeout /t 3 >nul
