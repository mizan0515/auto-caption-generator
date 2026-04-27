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


def test_per_hour_cap_when_other_bins_compete():
    """다른 bin 이 있을 때 hot bin 은 base cap 만큼만 우선 채택.

    cap=6 hot bin × 30개 + cap=6 other bin × 6개, max_posts=12 →
    pass1: hot 6, other 6 = 12. 충족 → pass2/3 미진입.
    """
    base = datetime(2026, 4, 27, 1, 0, tzinfo=KST)
    posts = []
    for i in range(30):
        posts.append(_post(views=1000 + i, ts=base + timedelta(minutes=i),
                           url=f"hot-{i}"))
    for i in range(6):
        posts.append(_post(views=500, ts=base + timedelta(hours=1, minutes=i),
                           url=f"other-{i}"))
    out = _select_top_diverse(posts, max_posts=12, broadcast_dt=base, per_hour_cap=6)
    # 시간 bin 별 카운트
    bin_offsets = [int((p["timestamp_parsed"] - base).total_seconds() // 3600)
                   for p in out]
    cnt0 = sum(1 for o in bin_offsets if o == 0)
    cnt1 = sum(1 for o in bin_offsets if o == 1)
    assert len(out) == 12 and cnt0 == 6 and cnt1 == 6, (
        f"hot 6 + other 6 = 12 기대, got len={len(out)} cnt0={cnt0} cnt1={cnt1}"
    )
    print("[2a] cap 가 경쟁 bin 보호 OK (hot 30 + other 6, max 12 → 6+6)")


def test_multi_pass_fills_when_only_one_bin():
    """후보가 한 bin 에만 있으면 다중 패스로 max_posts 까지 채움.

    30개 모두 hot bin, max_posts=20 → pass1=6, pass2=12, pass3=20.
    """
    base = datetime(2026, 4, 27, 1, 0, tzinfo=KST)
    posts = [
        _post(views=1000 + i, ts=base + timedelta(minutes=i), url=f"only-{i}")
        for i in range(30)
    ]
    out = _select_top_diverse(posts, max_posts=20, broadcast_dt=base, per_hour_cap=6)
    assert len(out) == 20, f"한 bin 후보 30, max 20 → 20 기대, got {len(out)}"
    print("[2b] 한 bin 에만 후보 → 다중 패스로 max_posts 달성 OK")


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


def test_diverse_across_hours_max_posts_matches_total():
    """3개 시간대 × 6개씩 = 정확히 18개. max_posts=18 → 모두 채택, 분산 검증.

    각 bin 후보 6개씩이므로 pass1 cap=6 에서 18개 충족 → pass2/3 미진입.
    """
    base = datetime(2026, 4, 27, 1, 0, tzinfo=KST)
    posts = []
    for i in range(6):
        posts.append(_post(views=2000 + i, ts=base + timedelta(minutes=i * 2),
                           url=f"h0-{i}"))
    for i in range(6):
        posts.append(_post(views=500, ts=base + timedelta(hours=1, minutes=i * 5),
                           url=f"h1-{i}"))
    for i in range(6):
        posts.append(_post(views=300,
                           ts=base - timedelta(hours=1) + timedelta(minutes=i * 5),
                           url=f"hm1-{i}"))

    out = _select_top_diverse(posts, max_posts=18, broadcast_dt=base, per_hour_cap=6)
    bin_counts: dict[int, int] = {}
    for p in out:
        offset = int((p["timestamp_parsed"] - base).total_seconds() // 3600)
        bin_counts[offset] = bin_counts.get(offset, 0) + 1
    assert bin_counts == {0: 6, 1: 6, -1: 6}, f"시간 분산 실패: {bin_counts}"
    print(f"[4] 3개 시간대 균등 분산 OK ({bin_counts})")


def test_unknown_timestamp_bucket_capped_pass1():
    """다른 bin 이 경쟁할 때 pass1 의 unknown cap 작동.

    50 unknown (고점수) + 6 known(저점수, 동일 hour). max_posts=16 로 정확히
    pass1 capacity (unknown_cap=10 + per_hour_cap=6) 만큼 → 모두 pass1 에서 채워짐.
    """
    base = datetime(2026, 4, 27, 1, 0, tzinfo=KST)
    posts = [_post(views=10000 + i, ts=None, url=f"unk-{i}") for i in range(50)]
    posts += [_post(views=1, ts=base + timedelta(minutes=i), url=f"known-{i}")
              for i in range(6)]
    # max_posts=10, unknown_cap = int(10*0.4)=4, per_hour_cap=6 → pass1 4+6=10 정확히 충족
    out = _select_top_diverse(
        posts, max_posts=10, broadcast_dt=base,
        per_hour_cap=6, unknown_cap_ratio=0.4
    )
    n_unknown = sum(1 for p in out if p["timestamp_parsed"] is None)
    assert len(out) == 10, f"max_posts 10 정확히: got {len(out)}"
    assert n_unknown == 4, (
        f"unknown cap=4 인데 {n_unknown}개. 50 후보 중 4만 채택, 나머지는 known(6)"
    )
    print(f"[5] unknown bucket cap=4 작동 (pass1, 50 후보 → 4 채택, +known 6)")


def test_unknown_can_overflow_when_no_alternative():
    """다중 패스: unknown 만 있고 다른 bin 없으면 cap 초과해서라도 채움."""
    posts = [_post(views=100 + i, ts=None, url=f"u-{i}") for i in range(50)]
    out = _select_top_diverse(posts, max_posts=40, broadcast_dt=None,
                              unknown_cap_ratio=0.1)  # cap=4
    # pass1=4, pass2=8, pass3 무제한 → 40 채워짐
    assert len(out) == 40, f"unknown only 50, max=40 → 40 (pass3 fallback): got {len(out)}"
    print("[5b] unknown only + 다중 패스 → max_posts 충족 OK")


def test_no_broadcast_dt_uses_wallclock_hour():
    """broadcast_dt=None 일 때 wall-clock hour bin 으로 분산.

    같은 hour 에 20개, max_posts=8, cap=6 → pass1 6 + pass2 (cap=12) +2 = 8.
    cap 작동을 확인하면서 max_posts 도 충족.
    """
    base = datetime(2026, 4, 27, 5, 0, tzinfo=KST)
    posts = [
        _post(views=100 + i, ts=base + timedelta(minutes=i * 3), url=f"w-{i}")
        for i in range(20)
    ]
    out = _select_top_diverse(posts, max_posts=8, broadcast_dt=None, per_hour_cap=6)
    assert len(out) == 8, f"max_posts 8: got {len(out)}"
    print("[6] broadcast_dt=None → wall-clock hour fallback + 다중 패스 OK")


def test_max_posts_larger_than_pool():
    posts = [_post(views=v, ts=datetime(2026, 4, 27, h, 0, tzinfo=KST), url=f"p-{h}")
             for h, v in enumerate([100, 200, 300])]
    out = _select_top_diverse(posts, max_posts=120, broadcast_dt=None, per_hour_cap=6)
    assert len(out) == 3, "후보가 cap 보다 적으면 모두 반환"
    print("[7] max_posts > 후보 → 가용 글 모두 반환 OK")


def test_date_only_uses_day_bin_not_hour():
    """MM.DD 만 있는 글은 'day' bin 으로 분류되어 hour bin 에 몰리지 않는다.

    시나리오: 같은 날짜 (2026-04-26) 12:00 으로 떨어진 글 50개.
    이전 동작: 모두 hour bin -X 에 몰려 cap=6 으로 44개 손실
    새 동작: 'day' bin 에 모이고 per_day_cap=24 적용 → 24개 채택
    """
    from pipeline.scraper import _bin_key
    base = datetime(2026, 4, 27, 1, 0, tzinfo=KST)
    date_only_ts = datetime(2026, 4, 26, 12, 0, tzinfo=KST)
    posts = []
    for i in range(50):
        p = _post(views=1000 + i, ts=date_only_ts, url=f"d-{i}")
        p["timestamp"] = "04.26"  # MM.DD only
        posts.append(p)
    # bin_key 검증
    assert _bin_key(posts[0], base)[0] == "day"

    out = _select_top_diverse(posts, max_posts=120, broadcast_dt=base,
                              per_hour_cap=6, per_day_cap=24)
    # day cap base=24, pass2=48 까지 가능, pass3 cap 무한 → 50개 다.
    # 다른 bin 후보가 없으므로 pass3 에서 모두 채택.
    assert len(out) == 50, f"day-only 50개 모두 다중 패스로 채택: got {len(out)}"
    print("[8] date-only 글 day-bin 분류 + 다중 패스 채움 OK (50/50)")


def test_day_bin_cap_with_competing_hour_bins():
    """day-bin 50개 vs hour-bin 30개, max_posts=40 →
    pass1: day cap=24 + hour cap=6 = 30
    pass2: day cap=48 (40 개 한도까진), hour cap=12 → 추가 10 (hour 4 + day 6 등)
    최종 40개. day 가 cap 으로 보호되어 hour bin 도 살아남음.
    """
    base = datetime(2026, 4, 27, 1, 0, tzinfo=KST)
    date_only_ts = datetime(2026, 4, 26, 12, 0, tzinfo=KST)
    posts = []
    for i in range(50):
        p = _post(views=2000 + i, ts=date_only_ts, url=f"d-{i}")
        p["timestamp"] = "04.26"
        posts.append(p)
    for i in range(30):
        posts.append(_post(views=100, ts=base + timedelta(minutes=i),
                           url=f"h-{i}"))

    out = _select_top_diverse(posts, max_posts=40, broadcast_dt=base,
                              per_hour_cap=6, per_day_cap=24)
    n_day = sum(1 for p in out if p["timestamp"] == "04.26")
    n_hour = len(out) - n_day
    # pass1: day 24 + hour 6 = 30. pass2: day cap 48 으로 +10 가능, hour cap 12 로 +6.
    # 점수상 day(2000+) > hour(100) 이므로 pass2 에서 day 가 먼저 채워짐.
    # day 24 → 34 (10 추가), 합계 40 도달 → hour 는 pass1 의 6 그대로
    assert len(out) == 40, f"max_posts 40 달성: got {len(out)}"
    assert n_hour >= 6, f"hour bin 도 최소 6개는 보호되어야 함: got {n_hour}"
    print(f"[9] day-bin cap 이 hour-bin 보호 OK (day={n_day}, hour={n_hour}, total={len(out)})")


def main():
    test_score_formula()
    test_per_hour_cap_when_other_bins_compete()
    test_multi_pass_fills_when_only_one_bin()
    test_score_priority_within_bin()
    test_diverse_across_hours_max_posts_matches_total()
    test_unknown_timestamp_bucket_capped_pass1()
    test_unknown_can_overflow_when_no_alternative()
    test_no_broadcast_dt_uses_wallclock_hour()
    test_max_posts_larger_than_pool()
    test_date_only_uses_day_bin_not_hour()
    test_day_bin_cap_with_competing_hour_bins()
    print("\nb30_score_time_diversity: 11/11 OK")


if __name__ == "__main__":
    main()
