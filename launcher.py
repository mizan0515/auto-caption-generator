"""
launcher.py — exe 진입점

PyInstaller로 패키징 후 실행 시:
  1. Streamlit 서버를 현재 프로세스에서 직접 기동 (subprocess 불필요)
  2. 브라우저를 자동으로 열어준다

개발 시에도 동일하게 동작한다:
  python launcher.py
"""

import sys
import os
import threading
import time
import webbrowser

PORT = 8501


def get_app_path() -> str:
    """app.py의 절대 경로를 반환한다."""
    if getattr(sys, "frozen", False):
        # PyInstaller 번들 내부 (sys._MEIPASS)
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "app.py")


def open_browser_delayed(delay: float = 2.5):
    """Streamlit이 뜨고 나면 브라우저를 연다."""
    time.sleep(delay)
    webbrowser.open(f"http://localhost:{PORT}")


def main():
    app_path = get_app_path()

    # 브라우저 자동 열기 (백그라운드)
    threading.Thread(target=open_browser_delayed, daemon=True).start()

    # Streamlit CLI를 직접 호출 (subprocess 없이)
    import streamlit.web.cli as stcli

    sys.argv = [
        "streamlit", "run", app_path,
        f"--server.port={PORT}",
        "--server.headless=true",
        "--global.developmentMode=false",
        "--browser.gatherUsageStats=false",
        "--server.fileWatcherType=none",   # exe에서는 파일 감시 불필요
    ]

    sys.exit(stcli.main())


if __name__ == "__main__":
    main()
