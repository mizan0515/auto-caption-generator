"""파이프라인 설정 관리"""

import json
import os
from pathlib import Path
from typing import Optional

CONFIG_FILENAME = "pipeline_config.json"

DEFAULT_CONFIG = {
    "target_channel_id": "a7e175625fdea5a7d98428302b7aa57f",
    "streamer_name": "탬탬",
    # 멀티 스트리머 설정 (리스트). None 이면 legacy 단일 스트리머 모드.
    # 형식: [{"channel_id": "...", "name": "...", "search_keywords": [...]}]
    "streamers": None,
    "poll_interval_sec": 300,
    "download_resolution": 144,
    "output_dir": "./output",
    "work_dir": "./work",
    "fmkorea_search_keywords": ["탬탬"],
    # 청크 분할 precedence (Phase A2):
    #   DEFAULT_CONFIG: chunk_max_tokens=None 이므로 신규/기본 실행은 chunk_max_chars=8000 경로.
    #   pipeline_config.json merge: user json 에 token 키가 없으면 이 None/8000 기본값을 상속한다.
    #   both-set: 두 키가 동시에 설정되면 token 우선. precedence: chunk_max_tokens > chunk_max_chars.
    #   main.py fallback: sparse cfg 를 넘겨도 chunk_max_chars=8000 / overlap=30 으로 동일 규칙 유지.
    #   계량 단위는 raw_block 글자수 또는 raw_block token 수이며, cues_to_txt 길이가 아니다.
    # chunk_size_experiment 결과: 청크당 ~8000자(약 10분) = 분당 0.6~0.7 타임라인 밀도
    # 참고: 150000 은 사실상 "어떤 VOD든 1청크" → 요약이 10개 내외로 제한됨
    "chunk_max_chars": 8000,
    "chunk_max_tokens": None,
    "chunk_tokenizer_encoding": "cl100k_base",
    "chunk_overlap_sec": 30,
    # 채팅 하이라이트 기반 자막 필터링 (B01):
    #   highlight_radius_sec: 하이라이트 ±N초 구간은 모든 자막 유지
    #   cold_sample_sec: 나머지 구간에서 N초당 1개 샘플링
    "highlight_radius_sec": 300,
    "cold_sample_sec": 30,
    # Claude 모델 설정:
    #   빈 문자열이면 CLI 기본 모델 사용 (보통 sonnet)
    #   "haiku" = 경량 테스트용, "sonnet" = 기본, "opus" = 최고 품질
    "claude_model": "",
    "claude_timeout_sec": 300,
    # Whisper watchdog (B05):
    #   whisper_stall_sec: 진행 콜백이 N초간 없으면 hang 으로 판정 → TimeoutError
    #   whisper_timeout_sec: 전체 실행 시간 상한. 0 = 무제한 (긴 VOD 보호 비활성).
    "whisper_stall_sec": 600,
    "whisper_timeout_sec": 0,
    "auto_cleanup": True,
    "fmkorea_max_pages": 3,
    "fmkorea_max_posts": 20,
    "fmkorea_enabled": True,
    # B11: VOD publish_date 가 N시간 이전이면 fmkorea 검색 스킵 (오래된 방송은
    # 커뮤니티 화제 자료가 거의 없어 네트워크 비용 대비 가치 낮음).
    # 0 이하면 시간 제한 비활성화 (모든 VOD 에 대해 fmkorea 시도).
    "fmkorea_max_age_hours": 48,
    # 최초 실행 시 기존 VOD 처리 정책
    #   null      : 첫 실행 때 대화형 질문 (TTY 없으면 skip_all로 폴백)
    #   "skip_all": 기존 VOD 모두 스킵, 이후 새 VOD만 처리
    #   "latest_n": 최신 N개만 처리, 나머지는 스킵
    "bootstrap_mode": None,
    "bootstrap_latest_n": 1,
    # 자동 퍼블리시: VOD 처리 성공 후 site/ 재빌드
    "publish_autorebuild": True,
    "publish_site_dir": "./site",
    # B12/B13 실험 기본값:
    #   experiments/ 스크립트가 sweep 돌릴 때 참조하는 테스트 VOD.
    #   experiment_test_vod  : 다운로드 + 자막이 work/<video_no>/ 에 이미 있어야 함
    #   experiment_limit_duration_sec : 빠른 반복 위해 앞 N초만 사용 (0 = 전체)
    "experiment_test_vod": "",
    "experiment_limit_duration_sec": 1800,
    "cookies": {"NID_AUT": "", "NID_SES": ""},
}


class ConfigError(ValueError):
    """pipeline_config.json 의 타입/값이 잘못되었을 때 발생한다.

    load_config() 가 merge 된 cfg 를 validate_config() 로 검사하다 raise 하며,
    CLI 엔트리포인트(pipeline/main.py) 는 이 예외를 잡아 traceback 없이 친절한
    한국어 안내를 출력하고 `sys.exit(2)` 한다 (B21).
    """
    pass


_VALID_CLAUDE_MODELS = {"", "haiku", "sonnet", "opus"}
_VALID_BOOTSTRAP_MODES = {None, "skip_all", "latest_n"}

# (field, positive_only). bool 은 isinstance(bool, int) 이므로 별도 배제.
# positive_only=True 면 value > 0 강제, False 면 value >= 0 허용 (0=비활성 의미).
_INT_FIELDS: list[tuple[str, bool]] = [
    ("poll_interval_sec", True),
    ("download_resolution", True),
    ("chunk_max_chars", True),
    ("chunk_overlap_sec", False),
    ("highlight_radius_sec", False),
    ("cold_sample_sec", True),
    ("claude_timeout_sec", True),
    ("whisper_stall_sec", False),
    ("whisper_timeout_sec", False),
    ("fmkorea_max_pages", False),
    ("fmkorea_max_posts", False),
    ("fmkorea_max_age_hours", False),
    ("bootstrap_latest_n", True),
    ("experiment_limit_duration_sec", False),
]


def validate_config(cfg: dict) -> None:
    """merge 된 cfg 의 타입/값을 검증. 실패 시 ConfigError.

    목적: 첫 실행에서 설정 실수를 바로 차단해 다운로드/전사에 30분 쓰고 나서
    해독 불가능한 traceback 으로 죽는 UX 를 없앤다 (B21).
    """
    errors: list[str] = []

    for field, positive in _INT_FIELDS:
        if field not in cfg:
            continue
        v = cfg[field]
        if isinstance(v, bool) or not isinstance(v, int):
            errors.append(
                f"  - '{field}': 정수여야 합니다. 현재 값: {v!r} ({type(v).__name__})"
            )
            continue
        if positive and v <= 0:
            errors.append(f"  - '{field}': 양의 정수여야 합니다. 현재 값: {v}")
        elif not positive and v < 0:
            errors.append(f"  - '{field}': 0 이상이어야 합니다. 현재 값: {v}")

    if "chunk_max_tokens" in cfg:
        v = cfg["chunk_max_tokens"]
        if v is not None and (
            isinstance(v, bool) or not isinstance(v, int) or v <= 0
        ):
            errors.append(
                f"  - 'chunk_max_tokens': 양의 정수 또는 null 이어야 합니다. 현재: {v!r}"
            )

    cm = cfg.get("claude_model", "")
    if cm not in _VALID_CLAUDE_MODELS:
        allowed = ", ".join(repr(x) for x in sorted(_VALID_CLAUDE_MODELS))
        errors.append(
            f"  - 'claude_model': 허용 값은 {allowed}. 현재: {cm!r} (오타 확인)"
        )

    bm = cfg.get("bootstrap_mode", None)
    if bm not in _VALID_BOOTSTRAP_MODES:
        errors.append(
            f"  - 'bootstrap_mode': null / 'skip_all' / 'latest_n' 중 하나여야 합니다. 현재: {bm!r}"
        )

    ck = cfg.get("cookies")
    if ck is not None and not isinstance(ck, dict):
        errors.append(
            f"  - 'cookies': 객체(dict)여야 합니다. 현재: {type(ck).__name__}"
        )

    kw = cfg.get("fmkorea_search_keywords")
    if kw is not None and not isinstance(kw, list):
        errors.append(
            f"  - 'fmkorea_search_keywords': 리스트여야 합니다. 현재: {type(kw).__name__}"
        )

    if errors:
        header = (
            f"pipeline_config.json 설정 오류 ({len(errors)}건)\n"
            f"파일: {_config_path()}\n"
        )
        raise ConfigError(header + "\n".join(errors))


def _config_path() -> Path:
    return Path(__file__).resolve().parent.parent / CONFIG_FILENAME


def load_config() -> dict:
    path = _config_path()
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            user_cfg = json.load(f)
        merged = {**DEFAULT_CONFIG, **user_cfg}
        validate_config(merged)
        return merged
    save_config(DEFAULT_CONFIG)
    return dict(DEFAULT_CONFIG)


def save_config(cfg: dict) -> None:
    path = _config_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def normalize_streamers(cfg: dict) -> list[dict]:
    """cfg 에서 스트리머 목록을 추출한다.

    - cfg["streamers"] 가 비어있지 않은 리스트이면 그대로 사용.
    - 그렇지 않으면 legacy target_channel_id + streamer_name 에서 단일 항목을 생성.
    - 반환: [{"channel_id": str, "name": str, "search_keywords": list[str]}]
    """
    raw = cfg.get("streamers")
    if raw and isinstance(raw, list):
        normalized = []
        for s in raw:
            normalized.append({
                "channel_id": s.get("channel_id", ""),
                "name": s.get("name", ""),
                "search_keywords": s.get("search_keywords", [s.get("name", "")]),
            })
        return normalized

    # Legacy single-streamer fallback
    channel_id = cfg.get("target_channel_id", "")
    name = cfg.get("streamer_name", "")
    keywords = cfg.get("fmkorea_search_keywords", [name] if name else [])
    return [{
        "channel_id": channel_id,
        "name": name,
        "search_keywords": keywords,
    }]


def derive_streamer_id(channel_id: Optional[str], name: Optional[str] = None) -> str:
    """channel_id 또는 name 으로부터 안정적인 streamer_id slug 를 생성한다."""
    if channel_id:
        import re
        safe = re.sub(r"[^0-9a-fA-F]", "", channel_id)
        if safe:
            return f"channel-{safe}"
    if name:
        import re
        slug = name.strip().lower()
        slug = re.sub(r"[\s/]+", "-", slug)
        slug = re.sub(r"[^a-z0-9가-힣\-_]", "", slug)
        return f"name-{slug}" if slug else "unknown-streamer"
    return "unknown-streamer"


def get_cookies(cfg: dict) -> dict:
    raw = cfg.get("cookies", {})
    cookies = {}
    if raw.get("NID_AUT"):
        cookies["NID_AUT"] = raw["NID_AUT"]
    if raw.get("NID_SES"):
        cookies["NID_SES"] = raw["NID_SES"]
    return cookies


def ensure_dirs(cfg: dict) -> None:
    os.makedirs(cfg["output_dir"], exist_ok=True)
    os.makedirs(cfg["work_dir"], exist_ok=True)
    os.makedirs(os.path.join(cfg["output_dir"], "logs"), exist_ok=True)


def validate_cookies(cfg: dict) -> bool:
    cookies = get_cookies(cfg)
    if not cookies:
        print("=" * 60)
        print("  ⚠  Chzzk 쿠키가 설정되지 않았습니다.")
        print("=" * 60)
        print()
        print("  쿠키 설정 방법:")
        print("  1. 크롬에서 https://chzzk.naver.com 로그인")
        print("  2. F12 → Application → Cookies → chzzk.naver.com")
        print("  3. NID_AUT, NID_SES 값을 복사")
        print(f"  4. {_config_path()} 파일의 cookies 필드에 붙여넣기")
        print()
        print("  또는 --setup-cookies 플래그로 대화형 설정:")
        print("  python -m pipeline.main --setup-cookies")
        print()
        return False
    return True


def interactive_cookie_setup() -> None:
    cfg = load_config()
    print("Chzzk 쿠키 설정")
    print("-" * 40)
    nid_aut = input("NID_AUT: ").strip()
    nid_ses = input("NID_SES: ").strip()
    cfg["cookies"]["NID_AUT"] = nid_aut
    cfg["cookies"]["NID_SES"] = nid_ses
    save_config(cfg)
    print(f"✓ 쿠키가 {_config_path()}에 저장되었습니다.")
