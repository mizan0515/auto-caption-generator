"""B20 offline verification - pipeline/_io_encoding.force_utf8_stdio() 회귀 테스트.

B14/B15 에서 도입된 DRY 헬퍼. 3개 entrypoint (pipeline.main, transcribe,
tray_app) + 모든 B17/B18/B19 실험에서 호출되지만 전용 테스트가 없었음.

커버 케이스:
1. 정상 경로 - reconfigure 가능 스트림에서 UTF-8 로 전환
2. None 스트림 (pythonw 환경에서 sys.stdout = None 가능)
3. reconfigure 미지원 스트림 (구버전 Python 또는 커스텀 IO)
4. reconfigure 가 OSError 던지는 경우 (파이프 리다이렉트)
5. reconfigure 가 ValueError 던지는 경우
6. 멱등성 - 두 번 호출해도 무해
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline._io_encoding import force_utf8_stdio  # noqa: E402


class _ReconfigurableStream:
    def __init__(self):
        self.calls: list[dict] = []
        self.encoding = "cp949"
        self.errors = "strict"

    def reconfigure(self, *, encoding=None, errors=None):
        self.calls.append({"encoding": encoding, "errors": errors})
        if encoding:
            self.encoding = encoding
        if errors:
            self.errors = errors


class _LegacyStream:
    """reconfigure 없는 스트림 (구버전 또는 커스텀)."""
    encoding = "cp949"


class _RaisingStream:
    def __init__(self, exc: Exception):
        self._exc = exc
        self.called = False

    def reconfigure(self, *, encoding=None, errors=None):
        self.called = True
        raise self._exc


def _with_stdio(stdout, stderr):
    """sys.stdout/stderr 를 교체했다가 복원."""
    original_out, original_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = stdout, stderr
    try:
        force_utf8_stdio()
    finally:
        sys.stdout, sys.stderr = original_out, original_err


def _case_happy_path() -> bool:
    out, err = _ReconfigurableStream(), _ReconfigurableStream()
    _with_stdio(out, err)
    ok = (
        out.calls == [{"encoding": "utf-8", "errors": "replace"}]
        and err.calls == [{"encoding": "utf-8", "errors": "replace"}]
        and out.encoding == "utf-8"
        and err.errors == "replace"
    )
    print(f"[happy_path] {'PASS' if ok else 'FAIL'} - out.calls={out.calls} err.calls={err.calls}")
    return ok


def _case_none_stream() -> bool:
    """pythonw.exe 환경에서 sys.stdout 가 None 인 경우."""
    try:
        _with_stdio(None, None)
    except Exception as e:
        print(f"[none_stream] FAIL - raised {type(e).__name__}: {e}")
        return False
    print("[none_stream] PASS - no exception on None streams")
    return True


def _case_legacy_no_reconfigure() -> bool:
    out, err = _LegacyStream(), _LegacyStream()
    try:
        _with_stdio(out, err)
    except Exception as e:
        print(f"[legacy_no_reconfigure] FAIL - raised {type(e).__name__}: {e}")
        return False
    ok = out.encoding == "cp949"  # 변경 안 됨
    print(f"[legacy_no_reconfigure] {'PASS' if ok else 'FAIL'} - encoding unchanged")
    return ok


def _case_reconfigure_raises_oserror() -> bool:
    out = _RaisingStream(OSError(22, "Invalid argument"))
    err = _RaisingStream(OSError(22, "Invalid argument"))
    try:
        _with_stdio(out, err)
    except Exception as e:
        print(f"[oserror_swallowed] FAIL - raised {type(e).__name__}: {e}")
        return False
    ok = out.called and err.called
    print(f"[oserror_swallowed] {'PASS' if ok else 'FAIL'} - reconfigure called & exception swallowed")
    return ok


def _case_reconfigure_raises_valueerror() -> bool:
    out = _RaisingStream(ValueError("bad encoding"))
    err = _RaisingStream(ValueError("bad encoding"))
    try:
        _with_stdio(out, err)
    except Exception as e:
        print(f"[valueerror_swallowed] FAIL - raised {type(e).__name__}: {e}")
        return False
    print("[valueerror_swallowed] PASS - ValueError swallowed")
    return True


def _case_idempotent() -> bool:
    out, err = _ReconfigurableStream(), _ReconfigurableStream()
    _with_stdio(out, err)
    _with_stdio(out, err)
    ok = len(out.calls) == 2 and all(c == {"encoding": "utf-8", "errors": "replace"} for c in out.calls)
    print(f"[idempotent] {'PASS' if ok else 'FAIL'} - 2 calls both idempotent")
    return ok


def _case_real_bytesio() -> bool:
    """실제 io.TextIOWrapper(BytesIO) 로 reconfigure 가 실제 동작하는지 확인."""
    buf = io.BytesIO()
    wrapper = io.TextIOWrapper(buf, encoding="cp949", errors="strict")
    original_out, original_err = sys.stdout, sys.stderr
    sys.stdout = wrapper
    sys.stderr = io.TextIOWrapper(io.BytesIO(), encoding="cp949", errors="strict")
    try:
        force_utf8_stdio()
        ok = sys.stdout.encoding.lower() == "utf-8" and sys.stdout.errors == "replace"
    finally:
        sys.stdout, sys.stderr = original_out, original_err
    print(f"[real_textiowrapper] {'PASS' if ok else 'FAIL'} - encoding switched to utf-8")
    return ok


def main() -> int:
    results = [
        _case_happy_path(),
        _case_none_stream(),
        _case_legacy_no_reconfigure(),
        _case_reconfigure_raises_oserror(),
        _case_reconfigure_raises_valueerror(),
        _case_idempotent(),
        _case_real_bytesio(),
    ]
    passed = sum(results)
    total = len(results)
    print(f"\nB20 verification: {passed}/{total} passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
