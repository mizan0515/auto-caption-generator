"""stdout/stderr UTF-8 강제 헬퍼 (B14/B15).

Windows cp949 콘솔에서 한글 description/help/log 가 깨지는 문제를 방지한다.
모든 entrypoint (pipeline/main.py, transcribe.py, tray_app.py) 진입부에서 호출.

side-effect-only. import 시점이 아닌 명시적 호출 시점에 작동하도록 함수로 노출.
pythonw / 파이프 리다이렉트 / reconfigure 미지원 환경에서는 무음 폴백.
"""

from __future__ import annotations

import sys


def force_utf8_stdio() -> None:
    """sys.stdout / sys.stderr 가 reconfigure 를 지원하면 UTF-8 + errors=replace 로 전환."""
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream and hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            # pythonw stdout=None / 파이프 리다이렉트 / 구버전 Python 등
            pass
