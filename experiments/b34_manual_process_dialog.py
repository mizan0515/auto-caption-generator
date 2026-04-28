"""B34 — 대시보드 수동 VOD 처리 다이얼로그 검증.

Dashboard._build_manual_process_cmd 가 사용자 입력 조합으로 정확한 argv 를
빌드하는지 검증. UI 자체는 tkinter 의존이라 본 테스트는 cmd 빌더 + 인자
조합 검증에 한정.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.dashboard import Dashboard  # noqa: E402


def _builder():
    """Dashboard 인스턴스를 mainloop 없이 만들고 cmd 빌더만 호출."""
    return Dashboard.__new__(Dashboard)._build_manual_process_cmd


def _has_flag(cmd: list, flag: str) -> bool:
    return flag in cmd


def _flag_value(cmd: list, flag: str) -> str | None:
    if flag not in cmd:
        return None
    return cmd[cmd.index(flag) + 1]


def _flag_values(cmd: list, flag: str) -> list[str]:
    """반복 가능한 flag 의 모든 값."""
    out = []
    for i, tok in enumerate(cmd):
        if tok == flag and i + 1 < len(cmd):
            out.append(cmd[i + 1])
    return out


def test_minimal_cmd_only_vod():
    cmd = _builder()("12940641")
    assert "--process" in cmd
    assert _flag_value(cmd, "--process") == "12940641"
    assert "--streamer-name" not in cmd
    assert "--search-keyword" not in cmd
    assert "--limit-duration" not in cmd
    print("[1] VOD only → --process 만 포함 OK")


def test_full_cmd_user_example():
    """사용자 예시 그대로:
    python -m pipeline.main --process 12940641 --streamer-name "플레임" --search-keyword "호종컵"
    """
    cmd = _builder()(
        "12940641", streamer_name="플레임", keywords=["호종컵"]
    )
    assert _flag_value(cmd, "--process") == "12940641"
    assert _flag_value(cmd, "--streamer-name") == "플레임"
    assert _flag_value(cmd, "--search-keyword") == "호종컵"
    assert "--limit-duration" not in cmd
    print("[2] 사용자 예시 (VOD + 스트리머 + 키워드 1개) OK")


def test_multi_keywords_repeated_flag():
    """검색 키워드 여러 개 → --search-keyword 가 여러 번 반복."""
    cmd = _builder()(
        "12940641", streamer_name="플레임", keywords=["호종컵", "탬탬", "케리아"]
    )
    vals = _flag_values(cmd, "--search-keyword")
    assert vals == ["호종컵", "탬탬", "케리아"], vals
    # main.py 의 argparse 가 nargs="+" 또는 action="append" 로 받음 — 반복 호출 형식
    print(f"[3] 키워드 3개 → --search-keyword 3회 반복 OK ({vals})")


def test_limit_duration_added_when_positive():
    cmd = _builder()("12940641", limit_duration_sec=1800)
    assert _flag_value(cmd, "--limit-duration") == "1800"
    print("[4] limit-duration > 0 → 인자 추가 OK")


def test_limit_duration_skipped_when_zero():
    cmd = _builder()("12940641", limit_duration_sec=0)
    assert "--limit-duration" not in cmd
    print("[5] limit-duration = 0 → 인자 미추가 OK")


def test_empty_keywords_list_skipped():
    cmd = _builder()("12940641", streamer_name="X", keywords=[])
    assert "--search-keyword" not in cmd
    assert _flag_value(cmd, "--streamer-name") == "X"
    print("[6] 빈 키워드 리스트 → --search-keyword 미추가 OK")


def test_none_options_omitted():
    cmd = _builder()(
        "12940641", streamer_name=None, keywords=None, limit_duration_sec=0
    )
    assert "--streamer-name" not in cmd
    assert "--search-keyword" not in cmd
    assert "--limit-duration" not in cmd
    print("[7] None 옵션은 모두 생략 OK")


def test_cmd_starts_with_python_module():
    cmd = _builder()("12940641")
    # [0] = python.exe, [1] = -m, [2] = pipeline.main, [3] = --process, [4] = VOD
    assert cmd[1] == "-m"
    assert cmd[2] == "pipeline.main"
    assert cmd[3] == "--process"
    assert cmd[4] == "12940641"
    print("[8] cmd prefix [python, -m, pipeline.main, --process, VOD] OK")


def test_full_combination():
    """모든 옵션 동시 사용."""
    cmd = _builder()(
        "12345678",
        streamer_name="가",
        keywords=["k1", "k2"],
        limit_duration_sec=600,
    )
    assert _flag_value(cmd, "--process") == "12345678"
    assert _flag_value(cmd, "--streamer-name") == "가"
    assert _flag_values(cmd, "--search-keyword") == ["k1", "k2"]
    assert _flag_value(cmd, "--limit-duration") == "600"
    print("[9] 전체 옵션 조합 OK")


def main():
    test_minimal_cmd_only_vod()
    test_full_cmd_user_example()
    test_multi_keywords_repeated_flag()
    test_limit_duration_added_when_positive()
    test_limit_duration_skipped_when_zero()
    test_empty_keywords_list_skipped()
    test_none_options_omitted()
    test_cmd_starts_with_python_module()
    test_full_combination()
    print("\nb34_manual_process_dialog: 9/9 OK")


if __name__ == "__main__":
    main()
