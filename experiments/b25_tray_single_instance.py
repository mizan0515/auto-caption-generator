"""B25 — tray_app 이중 실행 silent race 방지 회귀.

이전 버그: `tray_app.exe` 를 두 번 클릭하면 두 daemon 스레드가 같은
`pipeline_state.json` 에 경쟁 쓰기. 중복 다운로드, 상태 오염, 두 아이콘이
시스템 트레이에 동시 잔존. 아무 경고 없음 — admin UX 최악.

테스트 케이스:
1. _pid_alive(self pid) → True (살아 있는 프로세스)
2. _pid_alive(dead pid) → False (확실히 죽은 PID, 0 또는 매우 큰 값)
3. _pid_alive(-1), _pid_alive(0) → False (invalid PID 가드)
4. _acquire_lock: 파일 없으면 생성 + 현재 PID 기록
5. _acquire_lock: stale lockfile (dead PID) → 덮어씀, 예외 없음
6. _acquire_lock: live lockfile (현재 PID != self, alive) → AlreadyRunningError
7. _acquire_lock: 같은 PID(자기 자신)면 그냥 덮어씀 (재시작 허용)
8. _acquire_lock: 손상된 lockfile (파싱 불가) → stale 취급하고 덮어씀
9. _release_lock: 파일 지움, 두 번 호출해도 예외 없음 (멱등)
10. main() 이 AlreadyRunningError 를 포획해 SystemExit(3) + 대화상자 호출
11. 대화상자 메시지에 PID, lock_path 포함
12. ConfigError 경로(B24) 는 여전히 SystemExit(2) 로 차별 유지
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline._io_encoding import force_utf8_stdio  # noqa: E402
force_utf8_stdio()

from pipeline.config import ConfigError  # noqa: E402


def _case(name, fn):
    try:
        fn()
        print(f"  ✓ {name}")
        return True
    except AssertionError as e:
        print(f"  ✗ {name}: {e}")
        return False
    except Exception as e:
        print(f"  ✗ {name}: {type(e).__name__}: {e}")
        return False


def _fresh_tray_module():
    if "tray_app" in sys.modules:
        del sys.modules["tray_app"]
    import tray_app  # noqa
    return tray_app


def _tmp_lock() -> str:
    """tempfile.NamedTemporaryFile 로 path 만 얻고 즉시 지움 (테스트가 생성/삭제 검증)."""
    fd, path = tempfile.mkstemp(prefix="b25_lock_", suffix=".lock")
    os.close(fd)
    os.remove(path)
    return path


def test_pid_alive_self():
    tray_app = _fresh_tray_module()
    assert tray_app._pid_alive(os.getpid()) is True, "자기 자신 PID 가 살아있다고 판정되지 않음"


def test_pid_alive_dead():
    tray_app = _fresh_tray_module()
    # Windows 상위 PID 범위 중 절대 살아 있지 않을 값
    # (32-bit 상한 근처. 이전 세션 PID 가 우연히 맞을 확률 거의 0)
    dead = 0x7FFFFFFE
    assert tray_app._pid_alive(dead) is False, f"PID {dead} 가 살아있다고 잘못 판정됨"


def test_pid_alive_invalid():
    tray_app = _fresh_tray_module()
    assert tray_app._pid_alive(0) is False
    assert tray_app._pid_alive(-1) is False


def test_acquire_creates_new():
    tray_app = _fresh_tray_module()
    lock = _tmp_lock()
    try:
        tray_app._acquire_lock(lock)
        assert os.path.exists(lock)
        with open(lock, encoding="utf-8") as f:
            content = f.read().strip()
        assert str(os.getpid()) == content, f"PID 불일치: {content!r} vs {os.getpid()}"
    finally:
        tray_app._release_lock(lock)


def test_acquire_overwrites_stale():
    tray_app = _fresh_tray_module()
    lock = _tmp_lock()
    try:
        with open(lock, "w", encoding="utf-8") as f:
            f.write("2147483646")  # dead PID
        tray_app._acquire_lock(lock)  # 예외 없이 덮어써야
        with open(lock, encoding="utf-8") as f:
            assert f.read().strip() == str(os.getpid())
    finally:
        tray_app._release_lock(lock)


def test_acquire_blocks_on_live():
    tray_app = _fresh_tray_module()
    lock = _tmp_lock()
    try:
        # 다른 PID 이지만 살아 있는 것으로 가정 → _pid_alive 모킹
        with open(lock, "w", encoding="utf-8") as f:
            f.write("99999")  # 가상 PID
        with mock.patch.object(tray_app, "_pid_alive", return_value=True):
            try:
                tray_app._acquire_lock(lock)
            except tray_app.AlreadyRunningError as e:
                assert e.pid == 99999, f"pid 기대 99999, 실제 {e.pid}"
                assert e.lock_path == lock
                return
        raise AssertionError("AlreadyRunningError 가 발생하지 않음")
    finally:
        # live 로 가정했던 lock 도 수동 청소
        if os.path.exists(lock):
            os.remove(lock)


def test_acquire_allows_self_pid():
    tray_app = _fresh_tray_module()
    lock = _tmp_lock()
    try:
        with open(lock, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
        # 자기 자신 PID 는 중복 기동이 아니므로 허용 (재시작/재부팅 가정 최소화)
        tray_app._acquire_lock(lock)  # 예외 없어야
    finally:
        tray_app._release_lock(lock)


def test_acquire_treats_corrupt_as_stale():
    tray_app = _fresh_tray_module()
    lock = _tmp_lock()
    try:
        with open(lock, "w", encoding="utf-8") as f:
            f.write("not-a-number\ngarbage")
        tray_app._acquire_lock(lock)  # 손상은 stale 로 간주
        with open(lock, encoding="utf-8") as f:
            assert f.read().strip() == str(os.getpid())
    finally:
        tray_app._release_lock(lock)


def test_release_idempotent():
    tray_app = _fresh_tray_module()
    lock = _tmp_lock()
    tray_app._acquire_lock(lock)
    assert os.path.exists(lock)
    tray_app._release_lock(lock)
    assert not os.path.exists(lock)
    tray_app._release_lock(lock)  # 두 번째 호출 — 예외 없어야


def test_main_catches_already_running():
    tray_app = _fresh_tray_module()
    err = tray_app.AlreadyRunningError(12345, "C:/tmp/pipeline.tray.lock")
    captured = {}
    with mock.patch.object(tray_app, "PipelineTray", side_effect=err), \
         mock.patch.object(tray_app, "_show_fatal_dialog",
                           side_effect=lambda t, m: captured.update(t=t, m=m)):
        try:
            tray_app.main()
        except SystemExit as se:
            assert se.code == 3, f"exit code 3 기대, 실제 {se.code}"
            assert "이미 실행 중" in captured.get("t", "")
            assert "12345" in captured.get("m", "")
            assert "pipeline.tray.lock" in captured.get("m", "")
            return
    raise AssertionError("SystemExit(3) 가 발생하지 않음")


def test_config_error_still_exit_2():
    """B24 회귀: ConfigError 는 여전히 SystemExit(2), AlreadyRunningError 와 차별."""
    tray_app = _fresh_tray_module()
    with mock.patch.object(tray_app, "PipelineTray",
                           side_effect=ConfigError("bad cfg")), \
         mock.patch.object(tray_app, "_show_fatal_dialog"):
        try:
            tray_app.main()
        except SystemExit as se:
            assert se.code == 2, f"B24 회귀: ConfigError 는 exit 2 여야 함, 실제 {se.code}"
            return
    raise AssertionError("SystemExit(2) 가 발생하지 않음")


def main():
    cases = [
        ("pid_alive_self", test_pid_alive_self),
        ("pid_alive_dead", test_pid_alive_dead),
        ("pid_alive_invalid", test_pid_alive_invalid),
        ("acquire_creates_new", test_acquire_creates_new),
        ("acquire_overwrites_stale", test_acquire_overwrites_stale),
        ("acquire_blocks_on_live", test_acquire_blocks_on_live),
        ("acquire_allows_self_pid", test_acquire_allows_self_pid),
        ("acquire_treats_corrupt_as_stale", test_acquire_treats_corrupt_as_stale),
        ("release_idempotent", test_release_idempotent),
        ("main_catches_already_running", test_main_catches_already_running),
        ("config_error_still_exit_2", test_config_error_still_exit_2),
    ]
    print("B25 tray single-instance lock tests")
    passed = 0
    for name, fn in cases:
        if _case(name, fn):
            passed += 1
    print(f"\n결과: {passed}/{len(cases)} 통과")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())
