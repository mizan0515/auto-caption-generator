"""B27 — fmkorea Chromium 백엔드 검증.

검증 항목:
1. dispatch: scrape_fmkorea(scraper_mode="chromium") 가 _scrape_fmkorea_chromium 호출
2. fallback: playwright 미설치 환경 (ImportError 모킹) 에서 http 폴백
3. dispatch: scraper_mode="http" 는 그대로 _scrape_fmkorea_http 호출 (회귀)
4. invalid mode: ValueError 즉시
5. cooldown: 마커가 있으면 chromium/http 둘 다 [] 반환 (회귀)
6. user_data_dir: work_dir 부모에 .playwright-userdata 생성

선택 항목 (LIVE=1 환경에서만 실행):
7. 실제 fmkorea 검색 1회 — Chromium 으로 ≥5개 파싱 확인
"""

import os
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline import scraper  # noqa: E402


def test_dispatch_chromium_calls_chromium_backend():
    sentinel = [{"title": "X", "url": "u", "body_preview": "", "author": "",
                 "timestamp": "", "timestamp_parsed": None, "views": 0,
                 "comments": 0, "likes": 0}]
    with mock.patch.object(scraper, "_scrape_fmkorea_chromium", return_value=sentinel) as m_ch, \
         mock.patch.object(scraper, "_scrape_fmkorea_http") as m_http:
        out = scraper.scrape_fmkorea(["탬탬"], max_pages=1, max_posts=20,
                                     scraper_mode="chromium")
    assert m_ch.called, "chromium 모드인데 chromium 백엔드 미호출"
    assert not m_http.called, "chromium 모드인데 http 백엔드 호출됨"
    assert len(out) == 1 and out[0].title == "X"
    print("[1] dispatch chromium → chromium backend OK")


def test_dispatch_http_calls_http_backend():
    with mock.patch.object(scraper, "_scrape_fmkorea_http", return_value=[]) as m_http, \
         mock.patch.object(scraper, "_scrape_fmkorea_chromium") as m_ch:
        scraper.scrape_fmkorea(["탬탬"], max_pages=1, max_posts=20,
                               scraper_mode="http")
    assert m_http.called and not m_ch.called
    print("[2] dispatch http → http backend OK (회귀)")


def test_invalid_mode_raises():
    try:
        scraper.scrape_fmkorea(["탬탬"], scraper_mode="selenium")
    except ValueError as e:
        assert "selenium" in str(e)
        print("[3] invalid mode → ValueError OK")
        return
    raise AssertionError("invalid mode 인데 raise 안 됨")


def test_cooldown_returns_empty_for_both_modes():
    with tempfile.TemporaryDirectory() as td:
        # 쿨다운 마커 생성
        marker = Path(td) / scraper._COOLDOWN_FILENAME
        marker.write_text(str(time.time()), encoding="utf-8")
        for mode in ("http", "chromium"):
            with mock.patch.object(scraper, "_scrape_fmkorea_http") as m_http, \
                 mock.patch.object(scraper, "_scrape_fmkorea_chromium") as m_ch:
                out = scraper.scrape_fmkorea(["탬탬"], work_dir=td, scraper_mode=mode)
            assert out == []
            assert not m_http.called and not m_ch.called, (
                f"{mode}: 쿨다운인데 백엔드 호출됨"
            )
        print("[4] cooldown 마커 → 두 모드 모두 [] 반환, 백엔드 미호출 OK (회귀)")


def test_chromium_fallback_when_playwright_missing():
    """playwright import 실패 시 http 폴백."""
    # ImportError 강제
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("playwright"):
            raise ImportError("forced for test")
        return real_import(name, *args, **kwargs)

    sentinel = [{"title": "fallback-post", "url": "u", "body_preview": "",
                 "author": "", "timestamp": "", "timestamp_parsed": None,
                 "views": 0, "comments": 0, "likes": 0}]
    with mock.patch("builtins.__import__", side_effect=fake_import), \
         mock.patch.object(scraper, "_scrape_fmkorea_http", return_value=sentinel) as m_http:
        out = scraper._scrape_fmkorea_chromium(["탬탬"], max_pages=1, work_dir=None)
    assert m_http.called
    assert out == sentinel
    print("[5] playwright 미설치 → http 폴백 OK")


def test_user_data_dir_layout():
    with tempfile.TemporaryDirectory() as td:
        per_vod = os.path.join(td, "12925400")
        os.makedirs(per_vod)
        path = scraper._playwright_user_data_dir(per_vod)
        # 부모(td) 아래 .playwright-userdata
        assert os.path.dirname(path) == os.path.abspath(td), (
            f"expected sibling of per-vod dir, got {path}"
        )
        assert os.path.basename(path) == ".playwright-userdata"
    print("[6] user_data_dir 가 work_dir 부모 아래 .playwright-userdata 로 배치 OK")


def test_live_chromium_search():
    """LIVE=1 일 때만 실행. 실제 fmkorea 1쿼리로 ≥5개 파싱 확인."""
    if os.environ.get("LIVE") != "1":
        print("[7] LIVE=1 미설정 — 실제 검색 skip")
        return
    with tempfile.TemporaryDirectory() as td:
        per_vod = os.path.join(td, "live_test")
        os.makedirs(per_vod)
        posts = scraper.scrape_fmkorea(
            ["탬탬"], max_pages=1, max_posts=20,
            work_dir=per_vod, scraper_mode="chromium",
        )
        print(f"[7] LIVE chromium 검색 결과: {len(posts)}개")
        assert len(posts) >= 5, f"실제 검색이 5개 미만 — 차단/파싱 회귀 의심"


def main():
    test_dispatch_chromium_calls_chromium_backend()
    test_dispatch_http_calls_http_backend()
    test_invalid_mode_raises()
    test_cooldown_returns_empty_for_both_modes()
    test_chromium_fallback_when_playwright_missing()
    test_user_data_dir_layout()
    test_live_chromium_search()
    print("\nb27_fmkorea_chromium: 6/6 (+1 optional LIVE) OK")


if __name__ == "__main__":
    main()
