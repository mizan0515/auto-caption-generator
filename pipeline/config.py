"""파이프라인 설정 관리"""

import json
import os
from pathlib import Path

CONFIG_FILENAME = "pipeline_config.json"

DEFAULT_CONFIG = {
    "target_channel_id": "a7e175625fdea5a7d98428302b7aa57f",
    "streamer_name": "탬탬",
    "poll_interval_sec": 300,
    "download_resolution": 144,
    "output_dir": "./output",
    "work_dir": "./work",
    "fmkorea_search_keywords": ["탬탬"],
    "chunk_max_chars": 150000,
    "chunk_overlap_sec": 45,
    "claude_timeout_sec": 300,
    "auto_cleanup": True,
    "fmkorea_max_pages": 3,
    "fmkorea_max_posts": 20,
    "fmkorea_enabled": True,
    "cookies": {"NID_AUT": "", "NID_SES": ""},
}


def _config_path() -> Path:
    return Path(__file__).resolve().parent.parent / CONFIG_FILENAME


def load_config() -> dict:
    path = _config_path()
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            user_cfg = json.load(f)
        merged = {**DEFAULT_CONFIG, **user_cfg}
        return merged
    save_config(DEFAULT_CONFIG)
    return dict(DEFAULT_CONFIG)


def save_config(cfg: dict) -> None:
    path = _config_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


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
