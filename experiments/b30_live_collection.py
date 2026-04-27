"""B30 실사용 테스트 — 실제 fmkorea 에서 chromium 백엔드로 수집 후
각 필터 단계의 분포를 분석한다.

산출:
- raw / dedup / time-filter / top-K 선별 단계별 카운트
- 시간대 (방송 기준 hour offset) 분포 시각화 (텍스트 히스토그램)
- 점수 분포 (min/median/max/p90)
- 채택된 vs 누락된 글의 점수/시간 비교
- 발견된 비효율/개선 후보 메모

사용:
    python experiments/b30_live_collection.py
"""

import json
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline import scraper  # noqa: E402

KST = timezone(timedelta(hours=9))


def _hour_offset(pt: datetime, base: datetime) -> int | None:
    if pt is None:
        return None
    return int((pt - base).total_seconds() // 3600)


def _hist(values: list[int], width: int = 50) -> str:
    """텍스트 히스토그램 (시간 bin → count)"""
    if not values:
        return "(empty)"
    c = Counter(values)
    lo, hi = min(c), max(c)
    max_count = max(c.values())
    lines = []
    for k in range(lo, hi + 1):
        cnt = c.get(k, 0)
        bar = "█" * int(width * cnt / max_count) if max_count else ""
        lines.append(f"  hour {k:+3d} | {cnt:3d} {bar}")
    return "\n".join(lines)


def _stats(scores: list[int]) -> dict:
    if not scores:
        return {"n": 0}
    sorted_s = sorted(scores)
    return {
        "n": len(scores),
        "min": min(scores),
        "median": median(scores),
        "p90": sorted_s[int(len(sorted_s) * 0.9)],
        "max": max(scores),
        "mean": sum(scores) // len(scores),
    }


def main():
    broadcast_start_iso = "2026-04-26T17:05:10+09:00"
    broadcast_dt = datetime.fromisoformat(broadcast_start_iso)
    keywords = ["탬탬"]
    max_pages = 20
    max_posts = 120

    print(f"=== B30 LIVE 수집 테스트 ===")
    print(f"VOD broadcast_dt: {broadcast_dt.isoformat()}")
    print(f"keywords: {keywords}")
    print(f"max_pages: {max_pages}, max_posts: {max_posts}")
    print(f"backend: chromium (B27)")
    print()

    with tempfile.TemporaryDirectory() as td:
        per_vod = Path(td) / "live_test"
        per_vod.mkdir()

        t0 = datetime.now()
        # 백엔드 직접 호출 → raw post dict 리스트
        raw_posts = scraper._scrape_fmkorea_chromium(
            keywords, max_pages=max_pages, work_dir=str(per_vod)
        )
        elapsed = (datetime.now() - t0).total_seconds()
        print(f"[수집] elapsed={elapsed:.1f}s, raw={len(raw_posts)}개")

        if not raw_posts:
            print("⚠ 수집 결과 0개 — 차단/네트워크 이슈 가능")
            return

        # === Stage 1: 원본 ===
        raw_offsets = [_hour_offset(p.get("timestamp_parsed"), broadcast_dt)
                       for p in raw_posts]
        raw_offsets_known = [o for o in raw_offsets if o is not None]
        raw_unknown = sum(1 for o in raw_offsets if o is None)
        print(f"\n[stage 1: raw] {len(raw_posts)}개 (timestamp 미파싱 {raw_unknown}개)")

        # === Stage 2: dedup (URL 기준) ===
        seen = set()
        unique = []
        for p in raw_posts:
            if p["url"] not in seen:
                seen.add(p["url"])
                unique.append(p)
        print(f"[stage 2: dedup] {len(unique)}개 (중복 제거 {len(raw_posts)-len(unique)}개)")

        # === Stage 3: ±24h 시간 필터 ===
        window_start = broadcast_dt - timedelta(hours=24)
        window_end = broadcast_dt + timedelta(hours=24)
        filtered = []
        out_of_window = 0
        for p in unique:
            pt = p.get("timestamp_parsed")
            if pt is None:
                filtered.append(p)
            elif window_start <= pt <= window_end:
                filtered.append(p)
            else:
                out_of_window += 1
        print(f"[stage 3: ±24h 필터] {len(filtered)}개 (윈도우 밖 제외 {out_of_window}개)")

        # === Stage 3 분포 (선별 직전) ===
        print(f"\n[stage 3 시간 분포] (방송시각 ±24h 윈도우 기준)")
        offsets_pre = [_hour_offset(p.get("timestamp_parsed"), broadcast_dt)
                       for p in filtered]
        offsets_pre_known = [o for o in offsets_pre if o is not None]
        offsets_pre_unknown = sum(1 for o in offsets_pre if o is None)
        print(_hist(offsets_pre_known))
        print(f"  unknown timestamp: {offsets_pre_unknown}개")

        scores_pre = [scraper._score_post(p) for p in filtered]
        print(f"\n[stage 3 점수 분포] {_stats(scores_pre)}")

        # === Stage 4: _select_top_diverse ===
        selected = scraper._select_top_diverse(
            filtered, max_posts=max_posts, broadcast_dt=broadcast_dt,
            per_hour_cap=6, unknown_cap_ratio=0.25
        )
        print(f"\n[stage 4: top-{max_posts} 점수+시간분산] {len(selected)}개")

        sel_offsets = [_hour_offset(p.get("timestamp_parsed"), broadcast_dt)
                       for p in selected]
        sel_offsets_known = [o for o in sel_offsets if o is not None]
        sel_unknown = sum(1 for o in sel_offsets if o is None)
        print(_hist(sel_offsets_known))
        print(f"  unknown timestamp: {sel_unknown}개")

        scores_sel = [scraper._score_post(p) for p in selected]
        print(f"\n[stage 4 점수 분포] {_stats(scores_sel)}")

        # === 누락된 hot post 분석 ===
        # filtered 중 selected 에 없는 글들. 점수 상위가 있다면 cap 때문에 누락된 것.
        sel_urls = {p["url"] for p in selected}
        missed = [p for p in filtered if p["url"] not in sel_urls]
        missed_scored = sorted(missed, key=scraper._score_post, reverse=True)
        print(f"\n[누락 분석] 선별 안 된 글 중 점수 상위 5개:")
        for p in missed_scored[:5]:
            sc = scraper._score_post(p)
            pt = p.get("timestamp_parsed")
            off = _hour_offset(pt, broadcast_dt)
            off_s = f"{off:+d}" if off is not None else "N/A"
            print(f"  score={sc:5d} hour={off_s:>4s} ts={p.get('timestamp')!r:20s} "
                  f"v={p.get('views')} c={p.get('comments')} l={p.get('likes')} "
                  f"| {p['title'][:50]!r}")

        # === timestamp 파싱 실패 진단 ===
        ts_samples = Counter()
        for p in raw_posts[:50]:
            ts_samples[p.get("timestamp", "")] += 1
        print(f"\n[timestamp 원본 샘플 (top 20)]:")
        for ts, n in ts_samples.most_common(20):
            print(f"  {n:3d}x  {ts!r}")

        # === bin 별 cap 도달 여부 ===
        bin_count = Counter(sel_offsets_known)
        saturated = sorted([h for h, n in bin_count.items() if n >= 6])
        if saturated:
            print(f"\n[saturated bins (cap=6 도달)] {len(saturated)}개:")
            print(f"  hour offsets: {saturated}")

        # === 후보 시간 분포 vs 선별 시간 분포 비교 (집중도) ===
        print(f"\n[집중도 비교] hot hour 들의 후보 vs 선별:")
        pre_counter = Counter(offsets_pre_known)
        for h, _ in pre_counter.most_common(5):
            print(f"  hour {h:+3d}: 후보 {pre_counter[h]:3d} → 선별 {bin_count.get(h,0):3d}")

        # === 결과 JSON 저장 (재분석용) ===
        report = {
            "broadcast_dt": broadcast_start_iso,
            "elapsed_sec": elapsed,
            "stages": {
                "raw": len(raw_posts),
                "dedup": len(unique),
                "time_filtered": len(filtered),
                "selected": len(selected),
            },
            "selected_score_stats": _stats(scores_sel),
            "candidate_score_stats": _stats(scores_pre),
            "missed_top5": [
                {"score": scraper._score_post(p), "title": p["title"],
                 "hour_offset": _hour_offset(p.get("timestamp_parsed"), broadcast_dt),
                 "views": p.get("views"), "comments": p.get("comments"),
                 "likes": p.get("likes")}
                for p in missed_scored[:5]
            ],
            "saturated_bins": saturated,
        }
        out_path = PROJECT_ROOT / "experiments" / "results" / "_b30_live_collection_report.json"
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        print(f"\n📝 리포트 저장: {out_path}")


if __name__ == "__main__":
    main()
