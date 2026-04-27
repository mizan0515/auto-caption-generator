"""B30 — fmkorea 게시글 점수화 + 시간 분산 선별 검증.

목표:
- 단순 [:max_posts] 슬라이스가 hot 시간대(방송 직후 1시간 등)에 쏠리는
  문제를 점수 내림차순 + per-hour cap 그리디로 해결.
- 점수 공식: views + comments*10 + likes*5

검증:
1. 점수 공식 정확성
2. 한 시간대에 cap 이상 몰리지 않음
3. 점수 높은 글이 우선 채택됨
4. timestamp 없는 글은 unknown bucket cap 이내
5. broadcast_dt 미제공 시 wall-clock hour 기반 fallback
6. max_posts 가 후보보다 클 때 가용 글 모두 반환
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.scraper import _score_post, _select_top_diverse  # noqa: E402

KST = timezone(timedelta(hours=9))


def _post(views=0, comments=0, likes=0, ts: datetime | None = None, title="x", url=None) -> dict:
    return {
        "title": title,
        "url": url or f"u-{id(object())}-{views}-{comments}",
        "body_preview": "",
        "author": "",
        "timestamp": "",
        "timestamp_parsed": ts,
        "views": views,
        "comments": comments,
        "likes": likes,
    }


def test_score_formula():
    assert _score_post({"views": 100, "comments": 0, "likes": 0}) == 100
    assert _score_post({"views": 0, "comments": 5, "likes": 0}) == 50
    assert _score_post({"views": 0, "comments": 0, "likes": 4}) == 20
    assert _score_post({"views": 100, "comments": 5, "likes": 4}) == 100 + 50 + 20
    # None / 누락 → 0
    assert _score_post({}) == 0
    assert _score_post({"views": None, "comments": None, "likes": None}) == 0
    print("[1] score formula OK (views + comments*10 + likes*5)")


def test_per_hour_cap_blocks_pile_up():
    """한 시간대에 30개 후보 → cap=6 이면 그 시간대에서 6개만 선택"""
    base = datetime(2026, 4, 27, 1, 0, tzinfo=KST)
    posts = [
        _post(views=1000 + i, ts=base + timedelta(minutes=i % 60), url=f"hot-{i}")
        for i in range(30)
    ]
    out = _select_top_diverse(posts, max_posts=120, broadcast_dt=base, per_hour_cap=6)
    # 모두 같은 시간 bin (hour_offset=0) → cap 6 만 채택
    assert len(out) == 6, f"hot hour cap 6 인데 {len(out)}개 선택됨"
    print("[2] per-hour cap=6 정확히 적용 OK (30개 hot → 6개만)")


def test_score_priority_within_bin():
    """같은 bin 내에서 점수 높은 글이 우선"""
    base = datetime(2026, 4, 27, 1, 0, tzinfo=KST)
    posts = [
        _post(views=v, ts=base, url=f"v{v}") for v in [10, 500, 100, 999, 50]
    ]
    out = _select_top_diverse(posts, max_posts=3, broadcast_dt=base, per_hour_cap=10)
    chosen_views = [p["views"] for p in out]
    assert chosen_views == [999, 500, 100], f"점수 우선 정렬 실패: {chosen_views}"
    print("[3] bin 내 점수 내림차순 OK (top 3: 999, 500, 100)")


def test_diverse_across_hours():
    """여러 시간대에 분산: hot 시간대만 cap 차고 그 다음 시간대로 자연 흘러야"""
    base = datetime(2026, 4, 27, 1, 0, tzinfo=KST)
    posts = []
    # hour 0: 20개 (모두 점수 1000+). minute 0~38 → 모두 hour offset 0 bin.
    for i in range(20):
        posts.append(_post(views=2000 + i, ts=base + timedelta(minutes=i * 2),
                           url=f"h0-{i}"))
    # hour +1: 10개 (점수 500). +1h 0min ~ +1h 45min → 모두 hour offset 1 bin.
    for i in range(10):
        posts.append(_post(views=500, ts=base + timedelta(hours=1, minutes=i * 5),
                           url=f"h1-{i}"))
    # hour -1: 10개 (점수 300). -1h 0min ~ -1h-(-45min) = -15min → 모두 -1 bin.
    # 주의: floor div 라 -1h 5min(=-3900s) 은 -2 bin 으로 흘러감. 따라서 -1h 안쪽으로만.
    for i in range(10):
        posts.append(_post(views=300,
                           ts=base - timedelta(hours=1) + timedelta(minutes=i * 5),
                           url=f"hm1-{i}"))

    out = _select_top_diverse(posts, max_posts=120, broadcast_dt=base, per_hour_cap=6)
    # 시간 bin 별 카운트
    bin_counts: dict[int, int] = {}
    for p in out:
        offset = int((p["timestamp_parsed"] - base).total_seconds() // 3600)
        bin_counts[offset] = bin_counts.get(offset, 0) + 1
    # hot bin 6, +1 bin 6, -1 bin 6 → 18개
    assert bin_counts.get(0) == 6, f"hour 0 cap 위반: {bin_counts}"
    assert bin_counts.get(1) == 6, f"hour +1 cap 위반: {bin_counts}"
    assert bin_counts.get(-1) == 6, f"hour -1 cap 위반: {bin_counts}"
    assert len(out) == 18, f"총 18개여야 함 (3 bin x 6): {len(out)}"
    print(f"[4] 3개 시간대 분산 OK ({bin_counts})")


def test_unknown_timestamp_bucket_capped():
    """timestamp_parsed=None 글은 unknown bucket cap 이내만 채택"""
    base = datetime(2026, 4, 27, 1, 0, tzinfo=KST)
    # 50개 unknown 글 (모두 고점수) + 5개 정상
    posts = [
        _post(views=10000 + i, ts=None, url=f"unk-{i}") for i in range(50)
    ]
    posts += [_post(views=1, ts=base, url=f"known-{i}") for i in range(5)]
    out = _select_top_diverse(
        posts, max_posts=120, broadcast_dt=base, per_hour_cap=6, unknown_cap_ratio=0.25
    )
    unknown_count = sum(1 for p in out if p["timestamp_parsed"] is None)
    # unknown_cap = max(1, int(120*0.25)) = 30
    assert unknown_count == 30, f"unknown cap 30 인데 {unknown_count}개"
    # 나머지는 known 5개 다
    assert len(out) == 35, f"30 unknown + 5 known = 35, got {len(out)}"
    print(f"[5] unknown 글 cap=30 적용 OK (50 후보 → 30 채택)")


def test_no_broadcast_dt_uses_wallclock_hour():
    """broadcast_dt=None 일 때 wall-clock hour 로 분산"""
    base = datetime(2026, 4, 27, 5, 0, tzinfo=KST)
    posts = [
        _post(views=100 + i, ts=base + timedelta(minutes=i * 3), url=f"w-{i}")
        for i in range(20)
    ]
    out = _select_top_diverse(posts, max_posts=120, broadcast_dt=None, per_hour_cap=6)
    # 같은 hour (5시) bin → cap 6 만 채택
    assert len(out) == 6, f"broadcast_dt 없어도 wall-clock hour cap 적용: {len(out)}"
    print("[6] broadcast_dt=None → wall-clock hour fallback OK")


def test_max_posts_larger_than_pool():
    posts = [_post(views=v, ts=datetime(2026, 4, 27, h, 0, tzinfo=KST), url=f"p-{h}")
             for h, v in enumerate([100, 200, 300])]
    out = _select_top_diverse(posts, max_posts=120, broadcast_dt=None, per_hour_cap=6)
    assert len(out) == 3, "후보가 cap 보다 적으면 모두 반환"
    print("[7] max_posts > 후보 → 가용 글 모두 반환 OK")


def main():
    test_score_formula()
    test_per_hour_cap_blocks_pile_up()
    test_score_priority_within_bin()
    test_diverse_across_hours()
    test_unknown_timestamp_bucket_capped()
    test_no_broadcast_dt_uses_wallclock_hour()
    test_max_posts_larger_than_pool()
    print("\nb30_score_time_diversity: 7/7 OK")


if __name__ == "__main__":
    main()
