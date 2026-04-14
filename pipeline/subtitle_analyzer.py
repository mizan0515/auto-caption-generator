"""자막(SRT) 기반 하이라이트 시그널 추출

채팅 밀도와 별개로, 자막 본문 자체에서 "드라마틱한 구간"을 찾는다.
- 감정 어휘 밀도 (웃음, 욕설, 강조 표현)
- 인용문·따옴표 밀도 (극적 발화)
- 반복 강조 표현 (같은 단어 3+ 반복, !! ?? 등)
- 선언/핵심발화 패턴 ("~는 없다", "~이다" 단언조)

시간축은 자막 타임스탬프 기준 = 영상 시작 기준 상대시간 (채팅과 동일 축).
"""

import logging
import re
from collections import defaultdict

from .chunker import parse_srt

logger = logging.getLogger("pipeline")

# ───── 어휘 사전 (Korean streaming context) ─────

_EMPHASIS_WORDS = {
    # 강한 감탄/강조
    "진짜": 1.0, "완전": 1.0, "개": 1.5, "존나": 1.5, "씨발": 1.2, "미쳤": 2.0,
    "대박": 1.5, "레전드": 2.0, "와씨": 1.2, "헐": 0.8, "개쩔": 2.0,
    # 드라마틱 반전
    "근데": 0.5, "하지만": 0.5, "갑자기": 1.2, "결국": 1.0, "그런데": 0.5,
    # 단정/선언
    "무조건": 1.3, "절대": 1.3, "당연": 1.0, "분명": 1.0,
    # 라이브 스트림 특유
    "클립": 1.5, "편집": 1.2, "짤": 1.0,
}

_LAUGHTER_PATTERNS = [
    (re.compile(r"ㅋ{4,}"), 1.5),   # ㅋㅋㅋㅋ 이상
    (re.compile(r"ㅎ{4,}"), 1.0),
    (re.compile(r"!!+"), 1.0),
    (re.compile(r"\?\?+"), 1.0),
    (re.compile(r"\.\.\."), 0.3),
]

# 극적 발화 패턴 (단언조, 슬로건)
_DECLARATIVE_PATTERNS = [
    re.compile(r"[가-힣]+(?:는|은)\s+없다"),          # "프로는 없다"
    re.compile(r"[가-힣]+(?:은|는)\s+[가-힣]+이다"),   # "인생은 OO이다"
    re.compile(r"^내가\s+.+\s+한다"),                # "내가 ~ 한다"
    re.compile(r"[가-힣]+\s+선언"),
]


def _score_text(text: str) -> tuple[float, dict]:
    """한 자막 라인의 드라마틱 점수 + 세부"""
    score = 0.0
    detail = {"emphasis": [], "laughter": 0, "quotes": 0, "declarative": 0}

    # 감정 어휘
    for word, weight in _EMPHASIS_WORDS.items():
        if word in text:
            score += weight
            detail["emphasis"].append(word)

    # 웃음/느낌표 패턴
    for pat, weight in _LAUGHTER_PATTERNS:
        matches = pat.findall(text)
        if matches:
            score += weight * len(matches)
            detail["laughter"] += len(matches)

    # 인용문 (따옴표)
    quote_count = text.count('"') // 2 + text.count('"') // 2 + text.count("'") // 2
    if quote_count:
        score += 0.5 * quote_count
        detail["quotes"] = quote_count

    # 단정/선언 패턴
    for pat in _DECLARATIVE_PATTERNS:
        if pat.search(text):
            score += 2.0
            detail["declarative"] += 1

    return score, detail


def analyze_subtitle(srt_path: str, window_sec: int = 60) -> list[dict]:
    """SRT를 윈도우별로 스캔하여 드라마틱 점수 시계열 생성.

    반환: [{"window_start_sec": int, "window_hms": str, "score": float,
            "cue_count": int, "top_lines": [str, ...]}] — score 내림차순
    """
    cues = parse_srt(srt_path)
    if not cues:
        return []

    windows: dict[int, dict] = defaultdict(lambda: {"score": 0.0, "cues": [], "details": []})

    for cue in cues:
        text = " ".join(ln.strip() for ln in cue.text_lines if ln.strip())
        if not text:
            continue
        score, detail = _score_text(text)
        if score <= 0:
            continue

        bucket = (cue.start_ms // 1000) // window_sec * window_sec
        windows[bucket]["score"] += score
        windows[bucket]["cues"].append({"sec": cue.start_ms / 1000, "text": text, "score": score})
        windows[bucket]["details"].append(detail)

    # 정렬: 점수 내림차순
    result = []
    for start_sec, data in sorted(windows.items()):
        cues_sorted = sorted(data["cues"], key=lambda c: c["score"], reverse=True)
        h = start_sec // 3600
        m = (start_sec % 3600) // 60
        s = start_sec % 60
        result.append({
            "window_start_sec": start_sec,
            "window_hms": f"{h:02d}:{m:02d}:{s:02d}",
            "score": round(data["score"], 2),
            "cue_count": len(data["cues"]),
            "top_lines": [c["text"] for c in cues_sorted[:3]],
        })

    return result


def find_subtitle_peaks(srt_path: str, window_sec: int = 60, top_n: int = 15) -> list[dict]:
    """자막 점수 상위 N개 윈도우 반환 (채팅 피크와 대응)"""
    windows = analyze_subtitle(srt_path, window_sec)
    windows.sort(key=lambda w: w["score"], reverse=True)
    peaks = windows[:top_n]
    peaks.sort(key=lambda w: w["window_start_sec"])  # 시간순 재정렬
    return peaks


def format_subtitle_signal_for_prompt(peaks: list[dict], max_chars: int = 2500) -> str:
    """자막 피크를 프롬프트용으로 포맷"""
    if not peaks:
        return "(자막 기반 드라마틱 시그널 없음)"

    lines = ["## 자막 기반 드라마틱 구간 (감정/강조/인용 밀도 상위)"]
    for p in peaks:
        top = p["top_lines"][0] if p["top_lines"] else ""
        snippet = top[:70] + ("..." if len(top) > 70 else "")
        lines.append(
            f"- [{p['window_hms']}] 점수 {p['score']:.1f} / {p['cue_count']}개 발화 · "
            f"대표: \"{snippet}\""
        )

    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n... (이하 생략)"
    return text
