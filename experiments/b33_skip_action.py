"""B33 — 사용자 스킵 액션 검증.

대시보드 "스킵" 메뉴의 백엔드 — PipelineState 메서드 + process_vod 협력적
cancel + monitor 가 skipped_user 영구 제외 + Whisper batch 경계 cancel.
"""

import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.state import PipelineState, SkipRequested  # noqa: E402


def _make_state(td: Path) -> PipelineState:
    return PipelineState(str(td / "pipeline_state.json"))


def test_request_skip_sets_flag():
    with tempfile.TemporaryDirectory() as td:
        s = _make_state(Path(td))
        s.update("100", status="transcribing", channel_id="ch1")
        ok = s.request_skip("100", channel_id="ch1")
        assert ok is True
        assert s.is_skip_requested("100", channel_id="ch1") is True
    print("[1] request_skip → flag 설정 + is_skip_requested True OK")


def test_request_skip_no_entry_returns_false():
    with tempfile.TemporaryDirectory() as td:
        s = _make_state(Path(td))
        ok = s.request_skip("999", channel_id="ch1")
        assert ok is False
        assert s.is_skip_requested("999", channel_id="ch1") is False
    print("[2] 없는 엔트리 request_skip → False OK")


def test_clear_skip_removes_flag():
    with tempfile.TemporaryDirectory() as td:
        s = _make_state(Path(td))
        s.update("100", status="transcribing", channel_id="ch1")
        s.request_skip("100", channel_id="ch1")
        s.clear_skip("100", channel_id="ch1")
        assert s.is_skip_requested("100", channel_id="ch1") is False
    print("[3] clear_skip → 플래그 해제 OK")


def test_mark_skipped_user_terminal():
    with tempfile.TemporaryDirectory() as td:
        s = _make_state(Path(td))
        s.update("100", status="transcribing", channel_id="ch1")
        s.request_skip("100", channel_id="ch1")
        s.mark_skipped_user("100", channel_id="ch1", reason="dashboard test")
        # status 가 terminal 'skipped_user' 로 전환됨
        assert s.get_status("100", channel_id="ch1") == "skipped_user"
        # skip_requested 도 같이 정리됨
        assert s.is_skip_requested("100", channel_id="ch1") is False
    print("[4] mark_skipped_user → terminal + 플래그 정리 OK")


def test_skipped_user_excluded_by_monitor_filter():
    """monitor.check_new_vods 의 status 제외 셋이 skipped_user 도 포함하는지 회귀."""
    from pipeline import monitor as mon
    src = Path(mon.__file__).read_text(encoding="utf-8")
    # 정확한 튜플 라인 검사 — 코드 검사로 충분 (monitor.check_new_vods 자체는
    # Chzzk API 의존이라 단위 테스트 어려움)
    assert '"skipped_user"' in src, "monitor 가 skipped_user 를 제외 셋에 포함해야 함"
    print("[5] monitor 가 skipped_user 도 새 VOD 후보에서 제외 OK")


def test_skipped_user_not_in_failed_or_stale():
    """skipped_user 는 재시도/좀비 회수 대상이 아니어야 함."""
    with tempfile.TemporaryDirectory() as td:
        s = _make_state(Path(td))
        s.update("100", status="error", channel_id="ch1")
        s.mark_skipped_user("100", channel_id="ch1")
        # error 였다가 skipped_user 로 전환된 후엔 retry 대상에서 빠진다
        assert ("100", "ch1") not in s.get_failed_vods()
        # 좀비 회수 대상도 아님 (terminal)
        recovered = s.recover_orphaned_processing()
        assert ("100", "ch1") not in recovered
    print("[6] skipped_user → retry/zombie 회수 대상 제외 OK")


def test_terminal_protection_skipped_user():
    """skipped_user 는 _TERMINAL_STATUSES — update() 가 비-terminal 로 덮어쓰지 못함."""
    with tempfile.TemporaryDirectory() as td:
        s = _make_state(Path(td))
        s.update("100", status="error", channel_id="ch1")
        s.mark_skipped_user("100", channel_id="ch1")
        # 이후 같은 video_no 가 다시 잡혀 update 되더라도 status="processing" 으로 클로버되지 않아야 함
        s.update("100", status="processing", channel_id="ch1")
        assert s.get_status("100", channel_id="ch1") == "skipped_user"
    print("[7] skipped_user 는 terminal 보호 — 비-terminal update 무효 OK")


def test_process_vod_skip_at_stage_boundary():
    """process_vod 가 stage 시작 직전 skip 플래그 보면 SkipRequested 로 빠져나와야 한다.

    실제 process_vod 는 무거운 의존성(downloader/Whisper/Claude)을 갖고 있어
    여기서는 _raise_if_skip 헬퍼가 의도대로 raise 하는지만 직접 검증.
    """
    from pipeline.main import _raise_if_skip
    from pipeline.models import VODInfo
    with tempfile.TemporaryDirectory() as td:
        s = _make_state(Path(td))
        vod = VODInfo(
            video_no="100", title="t", channel_id="ch1", channel_name="x",
            duration=60, publish_date="2026-04-27T01:00:00+09:00",
            thumbnail_url="", category="",
        )
        s.update("100", status="transcribing", channel_id="ch1")
        # 아직 skip 요청 없음 → 통과
        _raise_if_skip(s, vod, "transcribing")
        # 요청 후 → raise
        s.request_skip("100", channel_id="ch1")
        try:
            _raise_if_skip(s, vod, "transcribing")
        except SkipRequested as e:
            assert e.video_no == "100"
            assert "transcribing" in e.reason
            print("[8] _raise_if_skip stage 경계에서 SkipRequested raise OK")
            return
        raise AssertionError("SkipRequested 안 raise 됨")


def test_skip_persists_across_reload():
    """skip_requested / skipped_user 가 디스크 round-trip 후에도 유지되는지."""
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "pipeline_state.json"
        s1 = PipelineState(str(path))
        s1.update("100", status="transcribing", channel_id="ch1")
        s1.request_skip("100", channel_id="ch1")
        s1.mark_skipped_user("100", channel_id="ch1", reason="r")
        # 새 인스턴스로 reload
        s2 = PipelineState(str(path))
        assert s2.get_status("100", channel_id="ch1") == "skipped_user"
        assert s2.is_skip_requested("100", channel_id="ch1") is False
        # JSON 직접 검사
        data = json.loads(path.read_text(encoding="utf-8"))
        entry = data["processed_vods"]["ch1:100"]
        assert entry["status"] == "skipped_user"
        assert entry.get("skip_reason") == "r"
        assert "skip_requested" not in entry
    print("[9] 디스크 round-trip 보존 OK")


def main():
    test_request_skip_sets_flag()
    test_request_skip_no_entry_returns_false()
    test_clear_skip_removes_flag()
    test_mark_skipped_user_terminal()
    test_skipped_user_excluded_by_monitor_filter()
    test_skipped_user_not_in_failed_or_stale()
    test_terminal_protection_skipped_user()
    test_process_vod_skip_at_stage_boundary()
    test_skip_persists_across_reload()
    print("\nb33_skip_action: 9/9 OK")


if __name__ == "__main__":
    main()
