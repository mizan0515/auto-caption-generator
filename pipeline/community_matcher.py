"""커뮤니티 글 ↔ 자막 매칭

커뮤니티 글 제목/본문에서 키워드를 추출한 뒤, 자막 청크에서 해당 키워드가
등장하는 시점을 찾아 "커뮤니티에서도 화제가 된 구간" 시그널로 제공한다.

시간축 불일치 문제 때문에 커뮤니티 글의 timestamp 는 믿지 않고,
오로지 "자막 본문과 키워드 교집합"으로만 판단한다.
"""

import logging
import re
from collections import Counter
from typing import Iterable

from .chunker import parse_srt, Cue
from .models import CommunityPost

logger = logging.getLogger("pipeline")

# 너무 일반적이라 시그널이 안 되는 토큰
_STOPWORDS = {
    "방송", "오늘", "어제", "스트리머", "탬탬", "탬탬버린", "채팅", "시청자",
    "저거", "이거", "그거", "우리", "진짜", "완전", "그냥", "그럼", "근데",
    "그리고", "하지만", "그래서", "지금", "아까", "바로", "요즘", "요새",
    "아이", "그래", "이거", "저기", "여기", "거기", "같은", "같이",
    "있는", "있다", "없다", "없는", "하는", "하면", "되면", "된다", "된거",
    # 구체적이지 않은 감정어
    "대박", "개웃겨", "ㅋㅋ", "ㅎㅎ", "ㅠㅠ",
}

# 한글 단어 + 영문 + 숫자 (2자 이상)
_TOKEN_RE = re.compile(r"[가-힣]{2,}|[a-zA-Z]{3,}|\d{2,}")


def _tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text) if t not in _STOPWORDS]


def extract_keywords(posts: Iterable[CommunityPost], top_n: int = 15, min_freq: int = 2) -> list[tuple[str, int]]:
    """커뮤니티 글들로부터 의미있는 키워드 추출.

    조건: 전체 글에서 min_freq 이상 등장한 토큰, 빈도순 top_n 개.
    """
    counter: Counter = Counter()
    for p in posts:
        text = (p.title or "") + " " + (p.body_preview or "")
        counter.update(_tokenize(text))

    # 빈도 min_freq 이상, 길이 2+ 보장
    filtered = [(w, c) for w, c in counter.most_common(top_n * 3) if c >= min_freq and len(w) >= 2]
    return filtered[:top_n]


def match_keywords_to_subtitle(
    srt_path: str,
    keywords: list[str],
    cues: list | None = None,
) -> dict[str, list[dict]]:
    """자막에서 각 키워드가 등장하는 시점 리스트 반환.

    반환: {"키워드": [{"tc": "00:12:34", "line": "...발화 내용..."}, ...]}

    B08: cues 인자 제공 시 parse_srt 스킵.
    """
    if cues is None:
        cues = parse_srt(srt_path)
    results: dict[str, list[dict]] = {kw: [] for kw in keywords}

    for cue in cues:
        text = " ".join(ln.strip() for ln in cue.text_lines if ln.strip())
        if not text:
            continue
        for kw in keywords:
            if kw in text:
                # ms → HH:MM:SS
                total_sec = cue.start_ms // 1000
                h = total_sec // 3600
                m = (total_sec % 3600) // 60
                s = total_sec % 60
                results[kw].append({
                    "tc": f"{h:02d}:{m:02d}:{s:02d}",
                    "sec": cue.start_ms / 1000,
                    "line": text,
                })

    return results


def build_community_signal(
    posts: list[CommunityPost],
    srt_path: str,
    max_keywords: int = 10,
    cues: list | None = None,
) -> dict:
    """커뮤니티 키워드 매칭 결과를 요약 프롬프트용으로 패키징.

    반환: {
      "keywords": [(kw, count), ...],           # 커뮤니티 빈도
      "matches": [{"kw": ..., "count_srt": N, "top_occurrences": [...]}],
      "hot_segments": [{"tc": ..., "keywords": [...], "line": ...}]  # 2개 이상 키워드가 매칭된 구간
    }
    """
    if not posts:
        return {"keywords": [], "matches": [], "hot_segments": []}

    keywords_with_freq = extract_keywords(posts, top_n=max_keywords)
    if not keywords_with_freq:
        logger.info("커뮤니티 키워드 추출 결과 없음")
        return {"keywords": [], "matches": [], "hot_segments": []}

    keywords = [k for k, _ in keywords_with_freq]
    matches = match_keywords_to_subtitle(srt_path, keywords, cues=cues)

    summary = []
    for kw, freq in keywords_with_freq:
        occ = matches.get(kw, [])
        if occ:
            summary.append({
                "kw": kw,
                "community_freq": freq,
                "srt_count": len(occ),
                "top_occurrences": occ[:3],  # 최대 3개
            })

    # 같은 자막 구간에 2+ 키워드가 동시 매칭되면 "뜨거운 구간"
    tc_to_keywords: dict[str, set] = {}
    tc_to_line: dict[str, str] = {}
    for kw, occs in matches.items():
        for o in occs:
            tc_to_keywords.setdefault(o["tc"], set()).add(kw)
            tc_to_line[o["tc"]] = o["line"]

    hot_segments = [
        {"tc": tc, "keywords": sorted(kws), "line": tc_to_line[tc]}
        for tc, kws in tc_to_keywords.items() if len(kws) >= 2
    ]
    hot_segments.sort(key=lambda x: x["tc"])

    logger.info(
        f"커뮤니티 매칭 완료: 키워드 {len(keywords)}개, "
        f"매칭된 키워드 {len(summary)}개, 교차 구간 {len(hot_segments)}개"
    )
    return {
        "keywords": keywords_with_freq,
        "matches": summary,
        "hot_segments": hot_segments,
    }


def format_community_signal_for_prompt(signal: dict, max_chars: int = 3000) -> str:
    """build_community_signal 결과를 프롬프트용 텍스트로 포맷"""
    if not signal.get("keywords"):
        return "(커뮤니티 매칭 시그널 없음)"

    lines = ["## 커뮤니티에서 자주 언급된 키워드 × 자막 매칭"]

    if signal.get("hot_segments"):
        lines.append("\n**여러 키워드가 교차하는 자막 구간** (커뮤니티 화제 + 실제 발화 교집합):")
        for seg in signal["hot_segments"][:10]:
            kw_str = ", ".join(seg["keywords"])
            snippet = seg["line"][:80] + ("..." if len(seg["line"]) > 80 else "")
            lines.append(f"- [{seg['tc']}] 매칭 키워드: {kw_str} | 발화: \"{snippet}\"")

    if signal.get("matches"):
        lines.append("\n**키워드별 자막 등장 빈도**:")
        for m in signal["matches"][:15]:
            lines.append(
                f"- `{m['kw']}` — 커뮤니티 {m['community_freq']}건 / 자막 {m['srt_count']}회"
            )

    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n... (이하 생략)"
    return text
