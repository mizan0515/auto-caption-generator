"""B24 — tray_app 이 ConfigError 를 잡아 친절한 대화상자로 종료하는지 회귀.

이전 버그: `tray_app.PipelineTray.__init__` 가 `load_config()` 를 호출하는데
`pipeline_config.json` 이 스키마 위반이면 `ConfigError` traceback 이 날것으로
터져 트레이가 조용히 죽음. 서비스 런처 UX 로는 최악.

테스트 케이스:
1. main() 이 ConfigError 를 잡아 SystemExit(2) 로 종료하는지
2. _show_fatal_dialog 가 호출되는지 (메시지에 에러 원문 포함)
3. ConfigError 이외 예외는 전파되는지 (잘못된 except 광역화 방지)
4. 정상 cfg 면 기존 경로대로 PipelineTray 인스턴스를 만들고 run() 까지 호출되는지
5. Non-Windows 폴백이 stderr 로 출력되는지
6. ctypes import 실패 시 stderr 폴백이 동작하는지
7. ConfigError 메시지 원문이 대화상자에 그대로 전달되는지
"""

from __future__ import annotations

import io
import sys
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
    """tray_app 을 fresh import. 테스트 간 patch 오염 방지."""
    if "tray_app" in sys.modules:
        del sys.modules["tray_app"]
    import tray_app  # noqa
    return tray_app


def test_main_catches_config_error():
    tray_app = _fresh_tray_module()
    err = ConfigError("invalid claude_model")
    with mock.patch.object(tray_app, "PipelineTray", side_effect=err), \
         mock.patch.object(tray_app, "_show_fatal_dialog") as dlg:
        try:
            tray_app.main()
        except SystemExit as se:
            assert se.code == 2, f"exit code 2 기대, 실제 {se.code}"
            assert dlg.called, "대화상자 호출 누락"
            return
    raise AssertionError("SystemExit 가 발생하지 않음")


def test_dialog_message_contains_error():
    tray_app = _fresh_tray_module()
    err = ConfigError("claude_model 값이 잘못됨: 'haiko'")
    captured = {}

    def fake_dlg(title, message):
        captured["title"] = title
        captured["message"] = message

    with mock.patch.object(tray_app, "PipelineTray", side_effect=err), \
         mock.patch.object(tray_app, "_show_fatal_dialog", side_effect=fake_dlg):
        try:
            tray_app.main()
        except SystemExit:
            pass
    assert "claude_model" in captured.get("message", ""), \
        f"에러 원문이 대화상자에 없음: {captured.get('message')}"
    assert "설정" in captured.get("title", ""), \
        f"title 에 '설정' 없음: {captured.get('title')}"


def test_non_config_error_propagates():
    tray_app = _fresh_tray_module()
    with mock.patch.object(tray_app, "PipelineTray", side_effect=RuntimeError("boom")):
        try:
            tray_app.main()
        except RuntimeError as e:
            assert "boom" in str(e)
            return
        except SystemExit:
            raise AssertionError("RuntimeError 가 SystemExit 로 삼켜짐 (과잉 포획)")
    raise AssertionError("RuntimeError 가 전파되지 않음")


def test_happy_path_calls_run():
    tray_app = _fresh_tray_module()
    fake_app = mock.Mock()
    with mock.patch.object(tray_app, "PipelineTray", return_value=fake_app):
        tray_app.main()
    assert fake_app.run.called, "정상 경로에서 app.run() 이 호출되지 않음"


def test_fallback_to_stderr_on_non_windows():
    tray_app = _fresh_tray_module()
    buf = io.StringIO()
    with mock.patch.object(tray_app.sys, "platform", "linux"), \
         mock.patch.object(tray_app.sys, "stderr", buf):
        tray_app._show_fatal_dialog("T", "M-body")
    out = buf.getvalue()
    assert "T" in out and "M-body" in out, f"stderr 폴백에 제목/본문 누락: {out!r}"


def test_fallback_when_ctypes_import_fails():
    tray_app = _fresh_tray_module()
    buf = io.StringIO()
    # ctypes import 를 실패시키기 위해 sys.modules 에 None 주입
    saved = sys.modules.get("ctypes")
    sys.modules["ctypes"] = None  # ImportError 유발
    try:
        with mock.patch.object(tray_app.sys, "platform", "win32"), \
             mock.patch.object(tray_app.sys, "stderr", buf):
            tray_app._show_fatal_dialog("T2", "M2")
    finally:
        if saved is not None:
            sys.modules["ctypes"] = saved
        else:
            sys.modules.pop("ctypes", None)
    out = buf.getvalue()
    assert "T2" in out and "M2" in out, f"ctypes 실패 시 stderr 폴백 누락: {out!r}"


def test_dialog_called_with_error_str():
    tray_app = _fresh_tray_module()
    err = ConfigError("multi-line\nmessage with detail")
    captured = {}
    with mock.patch.object(tray_app, "PipelineTray", side_effect=err), \
         mock.patch.object(tray_app, "_show_fatal_dialog",
                           side_effect=lambda t, m: captured.update(t=t, m=m)):
        try:
            tray_app.main()
        except SystemExit:
            pass
    assert "multi-line" in captured.get("m", ""), \
        f"multi-line 메시지가 전달되지 않음: {captured.get('m')}"
    assert "detail" in captured.get("m", "")


def main():
    cases = [
        ("main_catches_config_error", test_main_catches_config_error),
        ("dialog_message_contains_error", test_dialog_message_contains_error),
        ("non_config_error_propagates", test_non_config_error_propagates),
        ("happy_path_calls_run", test_happy_path_calls_run),
        ("fallback_to_stderr_on_non_windows", test_fallback_to_stderr_on_non_windows),
        ("fallback_when_ctypes_import_fails", test_fallback_when_ctypes_import_fails),
        ("dialog_called_with_error_str", test_dialog_called_with_error_str),
    ]
    print("B24 tray_app ConfigError handling tests")
    passed = 0
    for name, fn in cases:
        if _case(name, fn):
            passed += 1
    print(f"\n결과: {passed}/{len(cases)} 통과")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())
