"""B22 regression: merge_results fallback UX — prompt leak 방지 + 사용자 복구 가이드.

실측 결함 (output/12402235_...md):
  "## chunk_01 — 분석 실패: Claude CLI 실패 (code=1): 알 수 없는 오류" 뒤에
  "해당 구간은 건너뛰고 요약해주세요" 라는 LLM-facing 지시문이 그대로 노출.

이 파일은 call_claude_cached 를 monkeypatch 해서 오프라인으로 6 시나리오 검증.
"""
from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline._io_encoding import force_utf8_stdio
force_utf8_stdio()

from pipeline import summarizer
from pipeline.models import VODInfo


def _vod() -> VODInfo:
    return VODInfo(
        video_no="99999999",
        title="테스트 방송",
        channel_name="테스트",
        channel_id="ch",
        publish_date="2026-04-17T00:00:00+09:00",
        duration=1800,
        category="게임",
    )


def _install_claude_stub(monkey, behavior):
    """behavior: callable(user_prompt, system_prompt, timeout, model) -> str or raise."""
    calls: list[dict] = []

    def _stub(*, user_prompt, system_prompt, timeout, model=""):
        calls.append({"user": user_prompt, "system": system_prompt})
        return behavior(user_prompt, system_prompt, timeout, model)

    monkey.append(("call_claude_cached", summarizer.call_claude_cached))
    summarizer.call_claude_cached = _stub
    return calls


def _restore(monkey):
    for name, fn in monkey:
        setattr(summarizer, name, fn)


LEAK_PHRASE = "건너뛰고 요약해주세요"


def case_1_merge_success_with_failed_chunks():
    """성공 머지: Claude 는 LLM 지시문을 받지만, 반환값은 Claude 출력 그대로."""
    monkey = []
    calls = _install_claude_stub(monkey, lambda u, s, t, m: "# 최종 요약\n- 항목 1")
    try:
        chunks = [
            "## chunk_01 (00:00:00~00:15:00)\n\n- 정상 내용",
            "## chunk_02 — 분석 실패: Claude CLI 실패",
        ]
        out = summarizer.merge_results(chunks, _vod(), [], [], claude_timeout=30)
        assert out == "# 최종 요약\n- 항목 1", f"unexpected success output: {out[:80]}"
        assert LEAK_PHRASE in calls[0]["user"], "LLM 지시문이 user_prompt 에 prepend 되어야 함"
        assert "⚠ 주의: 전체 2개 청크 중 1개가 분석에 실패" in calls[0]["user"]
        print("PASS case_1: 성공 경로 — LLM 지시문은 프롬프트에만, 반환값에 누출 없음")
    finally:
        _restore(monkey)


def case_2_merge_fail_no_prompt_leak():
    """머지 실패: 반환된 리포트에 LLM 지시문 문구가 절대 없어야 함."""
    monkey = []
    _install_claude_stub(monkey, lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Claude CLI 실패 (code=1): 알 수 없는 오류")))
    try:
        chunks = ["## chunk_01 — 분석 실패: Claude CLI 실패 (code=1): 알 수 없는 오류"]
        out = summarizer.merge_results(chunks, _vod(), [], [], claude_timeout=30)
        assert LEAK_PHRASE not in out, f"LLM 지시문 누출! {out[:200]}"
        assert "통합 실패" in out
        assert "복구 방법" in out
        assert "--process 99999999" in out
        assert "Claude CLI 실패 (code=1)" in out, "실패 원인 요약 누락"
        print("PASS case_2: 머지 실패 — 프롬프트 누출 없음 + 복구 가이드 포함")
    finally:
        _restore(monkey)


def case_3_merge_fail_all_chunks_failed():
    """모든 청크 실패 + 머지 실패 — 실측 결함 재현 시나리오."""
    monkey = []
    _install_claude_stub(monkey, lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    try:
        chunks = ["## chunk_01 — 분석 실패: Claude CLI 실패 (code=1): 알 수 없는 오류"]
        out = summarizer.merge_results(chunks, _vod(), [], [], claude_timeout=30)
        assert LEAK_PHRASE not in out
        assert "실패 청크: 1/1" in out
        assert out.startswith("# 테스트 방송 — 자동 요약 (통합 실패)")
        print("PASS case_3: 전체 청크 실패 시에도 사용자 가이드 노출")
    finally:
        _restore(monkey)


def case_4_merge_success_no_failures():
    """실패 청크 0개: LLM 지시문 prepend 없어야 함 (토큰 낭비 방지)."""
    monkey = []
    calls = _install_claude_stub(monkey, lambda u, s, t, m: "# 최종")
    try:
        chunks = ["## chunk_01 (00:00:00~00:30:00)\n\n- 정상"]
        out = summarizer.merge_results(chunks, _vod(), [], [], claude_timeout=30)
        assert out == "# 최종"
        assert LEAK_PHRASE not in calls[0]["user"], "실패 0건인데 LLM 지시문 주입됨"
        assert "⚠ 주의" not in calls[0]["user"]
        print("PASS case_4: 실패 0건 — LLM 지시문 prepend 없음")
    finally:
        _restore(monkey)


def case_5_format_helper_empty():
    """_format_failure_notice_for_llm: failed=0 → 빈 문자열."""
    assert summarizer._format_failure_notice_for_llm(0, 5) == ""
    print("PASS case_5: 실패 0건 helper → empty")


def case_6_format_helper_nonzero():
    """_format_failure_notice_for_llm: failed>0 → 지시문 포함."""
    out = summarizer._format_failure_notice_for_llm(2, 5)
    assert "2개가 분석에 실패" in out
    assert "5개 청크" in out
    assert LEAK_PHRASE in out
    print("PASS case_6: 실패 N건 helper → 지시문 포함")


def case_7_reason_brief_no_traceback_leak():
    """reason 에 여러 줄 traceback 이 와도 첫 줄만 노출."""
    vod = _vod()
    chunks = ["## chunk_01 — 분석 실패: X"]
    reason = "first line error\nTraceback (most recent call last):\n  File ...\n    raise Something"
    out = summarizer._build_failure_report(vod, chunks, 1, 1, reason=reason)
    assert "first line error" in out
    assert "Traceback" not in out
    assert "raise Something" not in out
    print("PASS case_7: reason 다중줄 → 첫 줄만 노출, traceback 숨김")


if __name__ == "__main__":
    case_1_merge_success_with_failed_chunks()
    case_2_merge_fail_no_prompt_leak()
    case_3_merge_fail_all_chunks_failed()
    case_4_merge_success_no_failures()
    case_5_format_helper_empty()
    case_6_format_helper_nonzero()
    case_7_reason_brief_no_traceback_leak()
    print("\nAll 7 cases passed.")
