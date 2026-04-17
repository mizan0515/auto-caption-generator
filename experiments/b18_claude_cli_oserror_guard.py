"""B18 offline verification - claude_cli subprocess 예외 가드 검증.

pipeline/claude_cli.py 의 _call_claude_cli() 가 subprocess.run 레벨에서
발생하는 FileNotFoundError / PermissionError 를 명시적 RuntimeError 로
변환하는지 확인한다. shutil.which 와 subprocess.run 모두 monkeypatch.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline._io_encoding import force_utf8_stdio  # noqa: E402

force_utf8_stdio()

from pipeline import claude_cli  # noqa: E402


def _run_case(name: str, raise_exc: Exception, *, expect_substr: str) -> bool:
    original_run = claude_cli.subprocess.run
    original_which = claude_cli.shutil.which
    try:
        claude_cli.shutil.which = lambda _cmd: "C:\\fake\\claude.exe"  # type: ignore[assignment]

        def _raise(*_a, **_kw):
            raise raise_exc

        claude_cli.subprocess.run = _raise  # type: ignore[assignment]

        try:
            # retry 데코레이터를 우회하기 위해 wrapped 원본 함수 호출
            wrapped = claude_cli._call_claude_cli.__wrapped__  # type: ignore[attr-defined]
            wrapped("prompt", timeout=5, model="")
        except RuntimeError as e:
            msg = str(e)
            if expect_substr in msg:
                print(f"[{name}] PASS - RuntimeError: {msg[:120]}")
                return True
            print(f"[{name}] FAIL - RuntimeError msg mismatch: {msg}")
            return False
        except Exception as e:
            print(f"[{name}] FAIL - expected RuntimeError, got {type(e).__name__}: {e}")
            return False
        else:
            print(f"[{name}] FAIL - no exception raised")
            return False
    finally:
        claude_cli.subprocess.run = original_run
        claude_cli.shutil.which = original_which


def _test_which_missing() -> bool:
    """shutil.which 가 None 반환하면 기존 경로대로 RuntimeError."""
    original_which = claude_cli.shutil.which
    try:
        claude_cli.shutil.which = lambda _cmd: None  # type: ignore[assignment]
        try:
            wrapped = claude_cli._call_claude_cli.__wrapped__  # type: ignore[attr-defined]
            wrapped("prompt", timeout=5, model="")
        except RuntimeError as e:
            if "설치되어 있지 않" in str(e):
                print(f"[which_none_baseline] PASS - {str(e)[:80]}")
                return True
            print(f"[which_none_baseline] FAIL - msg mismatch: {e}")
            return False
        else:
            print("[which_none_baseline] FAIL - no exception")
            return False
    finally:
        claude_cli.shutil.which = original_which


def main() -> int:
    results = [
        _run_case(
            "file_not_found_race",
            FileNotFoundError(2, "No such file or directory", "claude"),
            expect_substr="실행 파일을 찾을 수 없습니다",
        ),
        _run_case(
            "permission_error",
            PermissionError(13, "Permission denied"),
            expect_substr="실행 실패",
        ),
        _run_case(
            "generic_oserror",
            OSError(8, "Exec format error"),
            expect_substr="실행 실패",
        ),
        _test_which_missing(),
    ]

    # TimeoutExpired 는 retry 데코레이터가 잡아야 하므로 여기서는 원래 예외가
    # wrapped 함수에서 그대로 전파되는지만 확인한다 (회귀 방지).
    original_run = claude_cli.subprocess.run
    original_which = claude_cli.shutil.which
    try:
        claude_cli.shutil.which = lambda _cmd: "C:\\fake\\claude.exe"  # type: ignore[assignment]

        def _raise_timeout(*_a, **_kw):
            raise subprocess.TimeoutExpired(cmd=["claude"], timeout=5)

        claude_cli.subprocess.run = _raise_timeout  # type: ignore[assignment]
        try:
            wrapped = claude_cli._call_claude_cli.__wrapped__  # type: ignore[attr-defined]
            wrapped("prompt", timeout=5, model="")
        except subprocess.TimeoutExpired:
            print("[timeout_passthrough] PASS - TimeoutExpired still propagates")
            results.append(True)
        except Exception as e:
            print(f"[timeout_passthrough] FAIL - wrong exception: {type(e).__name__}: {e}")
            results.append(False)
        else:
            print("[timeout_passthrough] FAIL - no exception")
            results.append(False)
    finally:
        claude_cli.subprocess.run = original_run
        claude_cli.shutil.which = original_which

    passed = sum(results)
    total = len(results)
    print(f"\nB18 verification: {passed}/{total} passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
