"""채팅 기반 하이라이트 추출 (chzzk_editor.py 분석 알고리즘 재사용)"""

import logging
import math
import re
from collections import defaultdict

logger = logging.getLogger("pipeline")

# ── 설정값 ──
WINDOW_SEC = 10       # 슬라이딩 윈도우(초)
PEAK_MERGE_SEC = 30   # 피크 병합 범위(초)
Z_THRESHOLD = 2.0     # Z-score 임계값

# ── 감정 키워드 가중치 ──
KEYWORD_WEIGHTS = {
    r'ㅋ{2,}':          1.0,
    r'ㅎ{2,}':          0.8,
    r'lol|lmao|ㄹㅇㅋ': 1.0,
    r'웃기|재밌|재미있': 0.8,
    r'ㄷ{2,}':          1.5,
    r'대박|미쳤|레전드|ㄹㅈㄷ': 1.5,
    r'와{2,}|우와+|오{3,}': 1.2,
    r'헐{1,}|헉{1,}':   1.2,
    r'wow|wtf|omg':     1.2,
    r'클립|편집|이거다|명장면': 2.5,
    r'저장|캡처|스샷':  2.0,
    r'하이라이트|짤':   2.0,
    r'ㅠ{2,}|ㅜ{2,}':   0.8,
    r'울었|눈물|감동':  1.0,
    r'ㅅㅂ|시발|존나|개ㅈ': 0.9,
    r'화남|열받|빡침':  0.9,
    r'후원|도네|구독|응원': 1.8,
    r'치어스|cheer':    1.8,
}

_compiled_keywords = [(re.compile(pat, re.IGNORECASE), w) for pat, w in KEYWORD_WEIGHTS.items()]


def score_message(msg: str) -> float:
    score = 0.0
    for pattern, weight in _compiled_keywords:
        if pattern.search(msg):
            score += weight
    return max(1.0, score)


def build_time_series(chats: list[dict], window_sec: int = WINDOW_SEC) -> dict:
    if not chats:
        return {"buckets": {}, "duration_sec": 0}

    buckets = defaultdict(lambda: {"count": 0, "score": 0.0})
    # 채팅이 정렬되어 있다는 보장이 없으므로 max() 로 계산
    duration_ms = max(c["ms"] for c in chats)

    for chat in chats:
        sec = chat["ms"] / 1000.0
        bucket = int(sec // window_sec) * window_sec
        buckets[bucket]["count"] += 1
        buckets[bucket]["score"] += score_message(chat["msg"])

    return {"buckets": dict(buckets), "duration_sec": duration_ms / 1000.0}


def z_score_peaks(buckets: dict, threshold: float = Z_THRESHOLD) -> list[dict]:
    if len(buckets) < 3:
        return []

    times = sorted(buckets.keys())
    counts = [buckets[t]["count"] for t in times]
    scores = [buckets[t]["score"] for t in times]

    def stats(lst):
        mean = sum(lst) / len(lst)
        var = sum((x - mean) ** 2 for x in lst) / len(lst)
        std = math.sqrt(var) if var > 0 else 1.0
        return mean, std

    count_mean, count_std = stats(counts)
    score_mean, score_std = stats(scores)
    max_count = max(counts) or 1
    max_score = max(scores) or 1

    peaks = []
    for t, cnt, sc in zip(times, counts, scores):
        z_count = (cnt - count_mean) / count_std
        z_score_val = (sc - score_mean) / score_std
        if z_count >= threshold or z_score_val >= threshold:
            composite = (cnt / max_count) * 0.4 + (sc / max_score) * 0.6
            peaks.append({
                "sec": t,
                "count": cnt,
                "raw_score": sc,
                "z_count": round(z_count, 2),
                "z_score": round(z_score_val, 2),
                "composite": round(composite, 4),
            })
    return peaks


def merge_peaks(peaks: list[dict], merge_sec: int = PEAK_MERGE_SEC) -> list[dict]:
    if not peaks:
        return []

    sorted_peaks = sorted(peaks, key=lambda p: p["sec"])
    merged = []
    group = [sorted_peaks[0]]

    for peak in sorted_peaks[1:]:
        if peak["sec"] - group[-1]["sec"] <= merge_sec:
            group.append(peak)
        else:
            best = max(group, key=lambda p: p["composite"])
            best["cluster_count"] = len(group)
            best["peak_count_sum"] = sum(p["count"] for p in group)
            merged.append(best)
            group = [peak]

    best = max(group, key=lambda p: p["composite"])
    best["cluster_count"] = len(group)
    best["peak_count_sum"] = sum(p["count"] for p in group)
    merged.append(best)

    return merged


def find_edit_points(chats: list[dict], top_n: int = 20) -> list[dict]:
    """메인 분석 파이프라인. composite 내림차순 정렬된 하이라이트 리스트 반환."""
    logger.info("채팅 분석 시작...")

    ts = build_time_series(chats, WINDOW_SEC)
    logger.info(f"  시계열 변환 완료: {len(ts['buckets'])}개 버킷")

    raw_peaks = z_score_peaks(ts["buckets"], Z_THRESHOLD)
    logger.info(f"  Z-score 피크 탐지: {len(raw_peaks)}개")

    merged = merge_peaks(raw_peaks, PEAK_MERGE_SEC)
    merged.sort(key=lambda p: p["composite"], reverse=True)

    for rank, p in enumerate(merged, 1):
        p["rank"] = rank

    logger.info(f"  최종 하이라이트: {len(merged)}개 (상위 {min(top_n, len(merged))}개 사용)")
    return merged[:top_n]


def get_chats_in_range(chats: list[dict], start_sec: float, end_sec: float) -> list[dict]:
    """특정 시간 범위의 채팅 반환"""
    start_ms = start_sec * 1000
    end_ms = end_sec * 1000
    return [c for c in chats if start_ms <= c["ms"] <= end_ms]


def format_chat_highlights_for_prompt(
    highlights: list[dict], chats: list[dict], context_sec: int = 30
) -> str:
    """하이라이트 구간의 채팅을 프롬프트용 텍스트로 포맷"""
    from .utils import sec_to_hms
    lines = []
    for h in highlights:
        sec = h["sec"]
        start = max(0, sec - context_sec)
        end = sec + context_sec
        nearby = get_chats_in_range(chats, start, end)

        lines.append(f"### [{sec_to_hms(sec)}] 하이라이트 (종합점수: {h['composite']:.4f}, 채팅수: {h['count']})")
        sample = nearby[:30]  # 최대 30개 채팅 샘플
        for c in sample:
            ts = sec_to_hms(c["ms"] / 1000.0)
            lines.append(f"  [{ts}] {c['nick']}: {c['msg']}")
        if len(nearby) > 30:
            lines.append(f"  ... 외 {len(nearby) - 30}개")
        lines.append("")

    return "\n".join(lines)
