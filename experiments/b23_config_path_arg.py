"""B23 — `--config` CLI 인자가 실제로 load_config() 에 전달되는지 회귀.

이전 버그: argparse 가 `--config` 를 파싱하지만 `cfg = load_config()` 는 무인자
호출이라 값이 무시됐다. 사용자가 `--config pipeline_config.prod.json` 을
넘겨도 조용히 기본 `pipeline_config.json` 이 로드됨. 관리자 UX 최악의
기만(silent override).

테스트 케이스:
1. 기본 경로(None) happy path — 기존 동작 유지
2. 커스텀 경로 전달 시 해당 파일의 값이 실제로 반영되는지
3. 커스텀 경로가 존재하지 않으면 그 경로에 DEFAULT 가 저장되는지
4. save_config 도 동일 경로에 쓰는지
5. 커스텀 경로의 ConfigError 가 정상 전파되는지
6. expanduser/resolve 가 적용되는지 (상대 경로 → 절대 경로)
7. save 후 재load 가 값 유지하는지 (왕복)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline._io_encoding import force_utf8_stdio  # noqa: E402
force_utf8_stdio()

from pipeline.config import (  # noqa: E402
    ConfigError,
    DEFAULT_CONFIG,
    load_config,
    save_config,
    _resolve_config_path,
)


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


TMP = Path(__file__).resolve().parent / "_b23_tmp"


def _cleanup():
    if TMP.exists():
        for f in TMP.iterdir():
            try:
                f.unlink()
            except FileNotFoundError:
                pass
        try:
            TMP.rmdir()
        except OSError:
            pass


def _ensure_tmp():
    _cleanup()
    TMP.mkdir(parents=True, exist_ok=True)


def test_default_path_still_works():
    # None 경로는 기존 동작 유지 — load 성공 (기본 pipeline_config.json 이 있거나 생성됨)
    cfg = load_config()
    assert "poll_interval_sec" in cfg
    assert isinstance(cfg["poll_interval_sec"], int)


def test_custom_path_values_respected():
    _ensure_tmp()
    p = TMP / "prod.json"
    p.write_text(
        json.dumps({"poll_interval_sec": 777, "claude_model": "haiku"}),
        encoding="utf-8",
    )
    cfg = load_config(config_path=p)
    assert cfg["poll_interval_sec"] == 777, f"실제 파일 값 반영 안 됨: {cfg.get('poll_interval_sec')}"
    assert cfg["claude_model"] == "haiku"
    _cleanup()


def test_missing_custom_path_creates_default():
    _ensure_tmp()
    p = TMP / "not_exist.json"
    assert not p.exists()
    cfg = load_config(config_path=p)
    assert p.exists(), "없는 경로에 DEFAULT 자동 저장이 동작하지 않음"
    assert cfg["claude_model"] == DEFAULT_CONFIG["claude_model"]
    _cleanup()


def test_save_writes_to_custom_path():
    _ensure_tmp()
    p = TMP / "written.json"
    cfg = dict(DEFAULT_CONFIG)
    cfg["poll_interval_sec"] = 99
    save_config(cfg, config_path=p)
    assert p.exists()
    loaded = json.loads(p.read_text(encoding="utf-8"))
    assert loaded["poll_interval_sec"] == 99
    _cleanup()


def test_custom_path_config_error_propagates():
    _ensure_tmp()
    p = TMP / "bad.json"
    p.write_text(
        json.dumps({"claude_model": "haiko"}),
        encoding="utf-8",
    )
    try:
        load_config(config_path=p)
    except ConfigError as e:
        assert "claude_model" in str(e)
        # 메시지에 실제 사용 경로가 찍혀야 (어느 파일이 틀렸는지)
        assert str(p.resolve()) in str(e) or str(p) in str(e), \
            f"오류 메시지에 경로 누락: {e}"
        _cleanup()
        return
    raise AssertionError("ConfigError 가 전파되지 않음")


def test_resolve_expands_relative():
    rel = Path("_b23_rel.json")
    resolved = _resolve_config_path(rel)
    assert resolved.is_absolute(), f"상대 경로가 절대화되지 않음: {resolved}"


def test_roundtrip_save_then_load():
    _ensure_tmp()
    p = TMP / "roundtrip.json"
    cfg = dict(DEFAULT_CONFIG)
    cfg["poll_interval_sec"] = 1234
    cfg["claude_model"] = "sonnet"
    save_config(cfg, config_path=p)
    reloaded = load_config(config_path=p)
    assert reloaded["poll_interval_sec"] == 1234
    assert reloaded["claude_model"] == "sonnet"
    _cleanup()


def main():
    cases = [
        ("default_path_still_works", test_default_path_still_works),
        ("custom_path_values_respected", test_custom_path_values_respected),
        ("missing_custom_path_creates_default", test_missing_custom_path_creates_default),
        ("save_writes_to_custom_path", test_save_writes_to_custom_path),
        ("custom_path_config_error_propagates", test_custom_path_config_error_propagates),
        ("resolve_expands_relative", test_resolve_expands_relative),
        ("roundtrip_save_then_load", test_roundtrip_save_then_load),
    ]
    print("B23 --config CLI arg propagation tests")
    passed = 0
    try:
        for name, fn in cases:
            if _case(name, fn):
                passed += 1
    finally:
        _cleanup()
    print(f"\n결과: {passed}/{len(cases)} 통과")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())
