"""B31 — fmkorea timestamp 파서 회귀 + 신규 포맷 (HH:MM, MM.DD) 검증.

B30 LIVE 수집에서 raw 400개 모두 timestamp_parsed=None 으로 떨어지는 사일런트
버그 발견 — fmkorea 가 'HH:MM' (오늘) / 'MM.DD' (올해) 포맷을 사용하는데
_parse_relative_time 이 둘 다 미지원이었음.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline import scraper  # noqa: E402

KST = timezone(timedelta(hours=9))


def _at(year, month, day, hour=0, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=KST)


def _patch_now(now: datetime):
    """`scraper.datetime.now(KST)` 를 모킹"""
    real_datetime = scraper.datetime
    fake = mock.MagicMock(wraps=real_datetime)
    fake.now = mock.MagicMock(return_value=now)
    fake.fromisoformat = real_datetime.fromisoformat
    fake.strptime = real_datetime.strptime
    return mock.patch.object(scraper, "datetime", fake)


def test_hhmm_today_past():
    """현재 02:30, '01:23' → 오늘 01:23"""
    now = _at(2026, 4, 27, 2, 30)
    with _patch_now(now):
        out = scraper._parse_relative_time("01:23")
    assert out == _at(2026, 4, 27, 1, 23), out
    print("[1] HH:MM 오늘 과거 → 오늘 OK")


def test_hhmm_today_future_becomes_yesterday():
    """현재 02:30, '19:03' → 어제 19:03"""
    now = _at(2026, 4, 27, 2, 30)
    with _patch_now(now):
        out = scraper._parse_relative_time("19:03")
    assert out == _at(2026, 4, 26, 19, 3), out
    print("[2] HH:MM 미래 → 어제로 보정 OK")


def test_mmdd_past_year():
    """현재 04-27, '04.26' → 올해 04-26 12:00"""
    now = _at(2026, 4, 27, 2, 30)
    with _patch_now(now):
        out = scraper._parse_relative_time("04.26")
    assert out == _at(2026, 4, 26, 12, 0), out
    print("[3] MM.DD 올해 과거 → 올해 12:00 OK")


def test_mmdd_future_year_wrap():
    """현재 04-27, '12.31' → 작년 12-31 12:00"""
    now = _at(2026, 4, 27, 2, 30)
    with _patch_now(now):
        out = scraper._parse_relative_time("12.31")
    assert out == _at(2025, 12, 31, 12, 0), out
    print("[4] MM.DD 미래 → 작년으로 wrap OK")


def test_mmdd_invalid_returns_none():
    """잘못된 날짜 (e.g., 02.30) → None"""
    now = _at(2026, 4, 27, 2, 30)
    with _patch_now(now):
        out = scraper._parse_relative_time("02.30")
    assert out is None, out
    print("[5] 잘못된 MM.DD → None OK")


def test_hhmm_invalid_returns_none():
    now = _at(2026, 4, 27, 2, 30)
    with _patch_now(now):
        out = scraper._parse_relative_time("25:99")
    assert out is None, out
    print("[6] 잘못된 HH:MM → None OK")


def test_existing_relative_formats_still_work():
    """N분/시간/일 전 포맷 회귀"""
    now = _at(2026, 4, 27, 12, 0)
    with _patch_now(now):
        assert scraper._parse_relative_time("5분 전") == now - timedelta(minutes=5)
        assert scraper._parse_relative_time("2시간 전") == now - timedelta(hours=2)
        assert scraper._parse_relative_time("3일 전") == now - timedelta(days=3)
        assert scraper._parse_relative_time("어제 14:30") == _at(2026, 4, 26, 14, 30)
    print("[7] 기존 포맷 (N분/시간/일 전, 어제 HH:MM) 회귀 OK")


def test_full_datetime_format_still_works():
    """YYYY.MM.DD HH:MM 회귀"""
    out = scraper._parse_relative_time("2026.04.14 15:00")
    assert out == _at(2026, 4, 14, 15, 0), out
    print("[8] YYYY.MM.DD HH:MM 회귀 OK")


def test_mmdd_with_time_existing_format():
    """MM.DD HH:MM (올해) 미래 보정"""
    now = _at(2026, 4, 27, 2, 30)
    with _patch_now(now):
        # 같은 해 미래 → 작년
        out = scraper._parse_relative_time("12.25 18:00")
    assert out == _at(2025, 12, 25, 18, 0), out
    print("[9] MM.DD HH:MM 미래 → 작년 wrap OK")


def main():
    test_hhmm_today_past()
    test_hhmm_today_future_becomes_yesterday()
    test_mmdd_past_year()
    test_mmdd_future_year_wrap()
    test_mmdd_invalid_returns_none()
    test_hhmm_invalid_returns_none()
    test_existing_relative_formats_still_work()
    test_full_datetime_format_still_works()
    test_mmdd_with_time_existing_format()
    print("\nb31_timestamp_parser: 9/9 OK")


if __name__ == "__main__":
    main()
