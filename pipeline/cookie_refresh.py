"""Chzzk 쿠키 자동 갱신 — 로컬 브라우저에서 NID_AUT/NID_SES 추출.

사용자가 평소처럼 Chrome/Edge/Firefox 에서 naver.com 에 로그인해 두면,
이 모듈이 해당 브라우저의 쿠키 저장소에서 NID_AUT/NID_SES 를 읽어
pipeline_config.json 의 cookies 필드를 갱신한다.

CLI:
    python -m pipeline.cookie_refresh               # auto (chrome→edge→firefox 순서)
    python -m pipeline.cookie_refresh --browser edge
    python -m pipeline.cookie_refresh --dry-run     # 읽기만, 저장 안 함

프로그램 호출:
    from pipeline.cookie_refresh import refresh_cookies
    ok, reason = refresh_cookies()  # True 면 config 갱신됨

주의:
- Chrome 실행 중이면 쿠키 DB 가 잠겨 읽기 실패할 수 있음 → Edge 또는 Firefox 대체.
- browser_cookie3 는 OS 별 DPAPI/keychain 복호화를 자동 처리.
- 네이버 도메인 (.naver.com) 의 NID_AUT/NID_SES 를 읽는다. chzzk.naver.com 하위에
  별도 세팅된 쿠키가 없어도 상위 도메인 쿠키가 그대로 상속된다.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger("pipeline.cookie_refresh")

_REQUIRED_COOKIES = ("NID_AUT", "NID_SES")
_NAVER_DOMAIN_SUFFIX = "naver.com"
_BROWSER_ORDER = ("chrome", "edge", "firefox", "brave", "chromium")


def _extract_from_browser(browser: str) -> dict[str, str]:
    """단일 브라우저에서 naver.com 쿠키 중 NID_AUT/NID_SES 추출.

    실패(미설치, DB lock, 복호화 실패)는 예외로 전파 — 호출측이 잡아서 다음 브라우저로 폴백.
    """
    import browser_cookie3  # type: ignore[import-untyped]

    loader = getattr(browser_cookie3, browser, None)
    if loader is None:
        raise ValueError(f"지원하지 않는 브라우저: {browser}")

    jar = loader(domain_name=_NAVER_DOMAIN_SUFFIX)
    found: dict[str, str] = {}
    for c in jar:
        if c.name in _REQUIRED_COOKIES and c.domain.endswith(_NAVER_DOMAIN_SUFFIX):
            # 같은 이름이 여러 도메인에 있을 수 있음 — 가장 최근(마지막) 값으로 덮어씀.
            found[c.name] = c.value
    return found


def extract_cookies(browser: str = "auto") -> tuple[dict[str, str], str]:
    """브라우저에서 쿠키를 읽어 반환.

    Args:
        browser: 'auto' 면 Chrome → Edge → Firefox → Brave → Chromium 순서로 시도.
                 명시 브라우저면 그것만 시도.

    Returns:
        (cookies_dict, source_browser_name) — cookies_dict 가 비어있으면 실패.
    """
    candidates = _BROWSER_ORDER if browser == "auto" else (browser,)
    last_err: Optional[Exception] = None
    for name in candidates:
        try:
            cookies = _extract_from_browser(name)
        except Exception as e:  # noqa: BLE001
            last_err = e
            logger.debug(f"{name} 쿠키 추출 실패: {e}")
            continue
        if all(k in cookies and cookies[k] for k in _REQUIRED_COOKIES):
            logger.info(f"{name} 에서 NID_AUT/NID_SES 추출 성공")
            return cookies, name
        logger.debug(f"{name} 에서 필요한 쿠키 누락: have={list(cookies)}")

    if last_err:
        hint = ""
        msg = str(last_err).lower()
        if "admin" in msg or "decryption" in msg or "unable to get key" in msg:
            hint = " (Chrome/Edge v127+ 는 관리자 권한 터미널에서 실행 필요 — 또는 Firefox 사용)"
        logger.warning(f"모든 브라우저에서 추출 실패 — 마지막 오류: {last_err}{hint}")
    else:
        logger.warning("네이버 로그인 세션을 가진 브라우저를 찾지 못함")
    return {}, ""


def refresh_cookies(
    browser: str = "auto",
    config_path: Optional[str | Path] = None,
    dry_run: bool = False,
) -> tuple[bool, str]:
    """브라우저 쿠키를 읽어 pipeline_config.json 의 cookies 필드를 갱신.

    Returns:
        (ok, reason) — ok=True 면 config 저장까지 성공 (dry_run 이면 저장 건너뜀).
    """
    from pipeline.config import load_config, save_config

    cookies, source = extract_cookies(browser=browser)
    if not cookies:
        return False, "브라우저에서 NID_AUT/NID_SES 를 찾지 못함 (naver.com 로그인 필요)"

    cfg = load_config(config_path=config_path)
    existing = cfg.get("cookies") or {}
    if (
        existing.get("NID_AUT") == cookies["NID_AUT"]
        and existing.get("NID_SES") == cookies["NID_SES"]
    ):
        return True, f"{source}: 쿠키가 이미 최신 상태"

    cfg["cookies"] = {"NID_AUT": cookies["NID_AUT"], "NID_SES": cookies["NID_SES"]}
    if dry_run:
        return True, f"{source}: 쿠키 추출 성공 (dry-run, 저장 안 함)"

    save_config(cfg, config_path=config_path)
    return True, f"{source}: pipeline_config.json 갱신 완료"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Chzzk 쿠키 자동 갱신 (브라우저 세션에서 추출)")
    parser.add_argument(
        "--browser",
        default="auto",
        choices=("auto", *_BROWSER_ORDER),
        help="어느 브라우저에서 읽을지 (기본 auto)",
    )
    parser.add_argument("--config", default=None, help="pipeline_config.json 경로 (기본 자동 탐색)")
    parser.add_argument("--dry-run", action="store_true", help="추출만 하고 저장 안 함")
    parser.add_argument("--verbose", "-v", action="store_true", help="DEBUG 로그")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    ok, reason = refresh_cookies(
        browser=args.browser,
        config_path=args.config,
        dry_run=args.dry_run,
    )
    print(reason)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
