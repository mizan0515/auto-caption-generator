"""B21 — pipeline_config.json early validation 회귀 테스트.

load_config() 가 merge 된 cfg 를 validate_config() 로 검사해 ConfigError 를
raise 하는 경로를 오프라인으로 덮는다. 목적은 "첫 실행에서 설정 실수를
바로 차단" — 다운로드/전사 30분 후 deep traceback UX 를 막는 것.

테스트 케이스:
1. DEFAULT_CONFIG happy path — validate 통과
2. claude_model 오타 ("haiko") → 실패 + 'claude_model' 메시지
3. poll_interval_sec 문자열 → 실패 + '정수' 메시지
4. chunk_max_chars 음수 → 실패 + '양의 정수' 메시지
5. chunk_overlap_sec 음수 → 실패 + '0 이상'
6. whisper_timeout_sec = 0 허용 (무제한 의미)
7. chunk_max_tokens = None 허용, 0 거부
8. bootstrap_mode 오타 → 실패
9. cookies 문자열 → 실패
10. fmkorea_search_keywords 문자열 → 실패
11. 다중 오류 aggregate — 메시지에 모두 포함
12. load_config() 가 ConfigError 를 전파 (tmp json 으로 검증)
13. bool 이 int 로 통과하지 않는지 회귀 — True 는 거부
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline._io_encoding import force_utf8_stdio  # noqa: E402
force_utf8_stdio()

from pipeline.config import (
    ConfigError,
    DEFAULT_CONFIG,
    validate_config,
    load_config,
)


def _case(name: str, fn):
    try:
        fn()
        print(f"  ✓ {name}")
        return True
    except AssertionError as e:
        print(f"  ✗ {name}: {e}")
        return False
    except Exception as e:
        print(f"  ✗ {name}: 예외 발생 {type(e).__name__}: {e}")
        return False


def test_default_config_happy_path():
    validate_config(dict(DEFAULT_CONFIG))  # raises if fails


def test_claude_model_typo():
    cfg = dict(DEFAULT_CONFIG)
    cfg["claude_model"] = "haiko"
    try:
        validate_config(cfg)
    except ConfigError as e:
        assert "claude_model" in str(e), f"msg 에 필드명 누락: {e}"
        assert "haiko" in str(e), f"msg 에 잘못된 값 누락: {e}"
        return
    raise AssertionError("ConfigError 가 발생하지 않음")


def test_poll_interval_string():
    cfg = dict(DEFAULT_CONFIG)
    cfg["poll_interval_sec"] = "300"
    try:
        validate_config(cfg)
    except ConfigError as e:
        assert "poll_interval_sec" in str(e)
        assert "정수" in str(e)
        return
    raise AssertionError("ConfigError 가 발생하지 않음")


def test_chunk_max_chars_negative():
    cfg = dict(DEFAULT_CONFIG)
    cfg["chunk_max_chars"] = -5
    try:
        validate_config(cfg)
    except ConfigError as e:
        assert "chunk_max_chars" in str(e)
        assert "양의 정수" in str(e)
        return
    raise AssertionError("ConfigError 가 발생하지 않음")


def test_chunk_overlap_negative():
    cfg = dict(DEFAULT_CONFIG)
    cfg["chunk_overlap_sec"] = -1
    try:
        validate_config(cfg)
    except ConfigError as e:
        assert "chunk_overlap_sec" in str(e)
        assert "0 이상" in str(e)
        return
    raise AssertionError("ConfigError 가 발생하지 않음")


def test_whisper_timeout_zero_ok():
    cfg = dict(DEFAULT_CONFIG)
    cfg["whisper_timeout_sec"] = 0  # 0 = 무제한 의미, 허용
    validate_config(cfg)


def test_chunk_max_tokens_none_ok_zero_rejected():
    cfg = dict(DEFAULT_CONFIG)
    cfg["chunk_max_tokens"] = None
    validate_config(cfg)

    cfg["chunk_max_tokens"] = 0
    try:
        validate_config(cfg)
    except ConfigError as e:
        assert "chunk_max_tokens" in str(e)
        return
    raise AssertionError("chunk_max_tokens=0 에서 ConfigError 가 발생하지 않음")


def test_bootstrap_mode_typo():
    cfg = dict(DEFAULT_CONFIG)
    cfg["bootstrap_mode"] = "latest"  # 'latest_n' 오타
    try:
        validate_config(cfg)
    except ConfigError as e:
        assert "bootstrap_mode" in str(e)
        assert "latest_n" in str(e)
        return
    raise AssertionError("ConfigError 가 발생하지 않음")


def test_cookies_wrong_type():
    cfg = dict(DEFAULT_CONFIG)
    cfg["cookies"] = "NID_AUT=xxx"
    try:
        validate_config(cfg)
    except ConfigError as e:
        assert "cookies" in str(e)
        return
    raise AssertionError("ConfigError 가 발생하지 않음")


def test_fmkorea_keywords_wrong_type():
    cfg = dict(DEFAULT_CONFIG)
    cfg["fmkorea_search_keywords"] = "탬탬,지누"
    try:
        validate_config(cfg)
    except ConfigError as e:
        assert "fmkorea_search_keywords" in str(e)
        return
    raise AssertionError("ConfigError 가 발생하지 않음")


def test_multiple_errors_aggregated():
    cfg = dict(DEFAULT_CONFIG)
    cfg["claude_model"] = "haiko"
    cfg["poll_interval_sec"] = "300"
    cfg["bootstrap_mode"] = "latest"
    try:
        validate_config(cfg)
    except ConfigError as e:
        msg = str(e)
        assert "claude_model" in msg
        assert "poll_interval_sec" in msg
        assert "bootstrap_mode" in msg
        assert "3건" in msg, f"집계 카운트 누락: {msg}"
        return
    raise AssertionError("ConfigError 가 발생하지 않음")


def test_bool_not_accepted_as_int():
    cfg = dict(DEFAULT_CONFIG)
    cfg["poll_interval_sec"] = True  # isinstance(True, int) is True
    try:
        validate_config(cfg)
    except ConfigError as e:
        assert "poll_interval_sec" in str(e)
        assert "정수" in str(e)
        return
    raise AssertionError("bool 이 정수로 잘못 통과됨")


def test_load_config_propagates_config_error(tmp_config_path=None):
    """load_config() 가 잘못된 json 파일을 만나면 ConfigError 를 raise 하는지."""
    from pipeline import config as config_mod

    original = config_mod._config_path
    tmp = Path(__file__).resolve().parent / "_b21_tmp_config.json"
    try:
        tmp.write_text(
            json.dumps({"claude_model": "haiko"}, ensure_ascii=False),
            encoding="utf-8",
        )
        config_mod._config_path = lambda: tmp
        try:
            load_config()
        except ConfigError as e:
            assert "claude_model" in str(e)
            return
        raise AssertionError("load_config 가 ConfigError 를 전파하지 않음")
    finally:
        config_mod._config_path = original
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def main():
    cases = [
        ("default_config_happy_path", test_default_config_happy_path),
        ("claude_model_typo", test_claude_model_typo),
        ("poll_interval_string", test_poll_interval_string),
        ("chunk_max_chars_negative", test_chunk_max_chars_negative),
        ("chunk_overlap_negative", test_chunk_overlap_negative),
        ("whisper_timeout_zero_ok", test_whisper_timeout_zero_ok),
        ("chunk_max_tokens_none_ok_zero_rejected", test_chunk_max_tokens_none_ok_zero_rejected),
        ("bootstrap_mode_typo", test_bootstrap_mode_typo),
        ("cookies_wrong_type", test_cookies_wrong_type),
        ("fmkorea_keywords_wrong_type", test_fmkorea_keywords_wrong_type),
        ("multiple_errors_aggregated", test_multiple_errors_aggregated),
        ("bool_not_accepted_as_int", test_bool_not_accepted_as_int),
        ("load_config_propagates_config_error", test_load_config_propagates_config_error),
    ]
    print("B21 config validation tests")
    passed = 0
    for name, fn in cases:
        if _case(name, fn):
            passed += 1
    print(f"\n결과: {passed}/{len(cases)} 통과")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())
