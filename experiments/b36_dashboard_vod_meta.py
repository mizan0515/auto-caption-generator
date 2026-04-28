"""B36 — 대시보드 VOD 컬럼 + 비고 가독성 개선 검증.

검증:
1. _format_publish_date — ISO / 공백 구분 / 날짜만 / None / 빈문자열 / garbage
2. state.update 의 title/publish_date 보존 (entry.update kwargs 패턴)
3. terminal status 보호 시에도 title/publish_date 유지
"""

import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.dashboard import _format_publish_date  # noqa: E402
from pipeline.state import PipelineState  # noqa: E402


def test_format_publish_date_iso_with_tz():
    assert _format_publish_date("2026-04-26T17:05:10+09:00") == "04-26 17:05"
    print("[1] ISO + tz → '04-26 17:05' OK")


def test_format_publish_date_space_separator():
    assert _format_publish_date("2026-04-26 17:05:10") == "04-26 17:05"
    print("[2] 공백 구분 → '04-26 17:05' OK")


def test_format_publish_date_date_only():
    assert _format_publish_date("2026-04-26") == "04-26"
    print("[3] 날짜만 → '04-26' (시각 없이) OK")


def test_format_publish_date_empty_or_none():
    assert _format_publish_date("") == ""
    assert _format_publish_date(None) == ""
    print("[4] 빈/None → '' OK")


def test_format_publish_date_garbage_fallback():
    # 알 수 없는 포맷 → 16자 잘림 그대로 반환
    out = _format_publish_date("garbage-input")
    assert out == "garbage-input"[:16]
    print("[5] 알 수 없는 포맷 → 원문 16자 잘림 OK")


def test_state_preserves_title_and_publish_date():
    """첫 update 에 title/publish_date 박으면 이후 update 에서도 entry 에 보존되는지."""
    with tempfile.TemporaryDirectory() as td:
        s = PipelineState(str(Path(td) / "pipeline_state.json"))
        s.update(
            "100", status="collecting", channel_id="ch1",
            title="[호종컵] 케리아 출장", publish_date="2026-04-26T17:05:10+09:00",
        )
        # 이후 다음 stage update — title/publish_date 인자 없이 호출
        s.update("100", status="transcribing", channel_id="ch1")
        # entry 에 title/publish_date 보존되어 있어야 함 (entry.update kwargs 패턴)
        s2 = PipelineState(str(Path(td) / "pipeline_state.json"))
        assert s2.get_status("100", channel_id="ch1") == "transcribing"
        # 직접 _data 확인 (디스크 reload 후)
        entry = s2._data["processed_vods"].get("ch1:100", {})
        assert entry.get("title") == "[호종컵] 케리아 출장"
        assert entry.get("publish_date") == "2026-04-26T17:05:10+09:00"
    print("[6] state.update 가 title/publish_date 보존 OK")


def test_state_terminal_protection_keeps_meta():
    """terminal status 진입 후 비-terminal update 시도 → meta 도 함께 보존."""
    with tempfile.TemporaryDirectory() as td:
        s = PipelineState(str(Path(td) / "pipeline_state.json"))
        s.update(
            "100", status="collecting", channel_id="ch1",
            title="t", publish_date="2026-04-26",
        )
        s.mark_skipped_user("100", channel_id="ch1")
        # terminal 진입 후 update 시도 → preserved 경로 진입
        s.update("100", status="processing", channel_id="ch1")
        entry = s._data["processed_vods"]["ch1:100"]
        assert entry["status"] == "skipped_user"  # terminal 보호
        assert entry.get("title") == "t"  # meta 도 보존
        assert entry.get("publish_date") == "2026-04-26"
    print("[7] terminal 보호 경로에서도 title/publish_date 유지 OK")


def main():
    test_format_publish_date_iso_with_tz()
    test_format_publish_date_space_separator()
    test_format_publish_date_date_only()
    test_format_publish_date_empty_or_none()
    test_format_publish_date_garbage_fallback()
    test_state_preserves_title_and_publish_date()
    test_state_terminal_protection_keeps_meta()
    print("\nb36_dashboard_vod_meta: 7/7 OK")


if __name__ == "__main__":
    main()
