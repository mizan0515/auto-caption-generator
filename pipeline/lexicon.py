"""Per-streamer 고유명사/신조어 어휘 빌더.

목적:
- Whisper initial_prompt 에 주입해 고유명사 오인식을 줄인다.
- Claude 요약 단계의 cross-check 힌트로 쓴다.
- 사후 교정 스크립트(scripts/recorrect_reports.py) 가 참조.

소스 (모두 이미 pipeline 이 수집 중 — 추가 네트워크 없음):
1. 채팅 로그 — work/<video_no>/<video_no>_chat.log.json 의 msg 에서 빈출 고유명사 후보 추출.
   채팅은 사용자가 직접 타이핑한 텍스트라 고유명사 표기의 ground-truth 에 가깝다.
2. 커뮤니티 포스트 — title + body 의 한글/영문 토큰.
3. VOD 제목 — 자연스럽게 게임명/이벤트/별명 포함.
4. 채널명 — streamer display name.

(옵션) 나무위키: `build_lexicon(..., fetch_namuwiki=True)` 로 활성화. 실패 시 무시.

캐시: .cache/lexicon/<channel_id>.json (7일 TTL). 강제 재빌드는 `rebuild=True`.

Whisper initial_prompt 는 ~224 토큰 제약이 있으니 상위 N개만 반환 (기본 30).
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from collections import Counter
from pathlib import Path
from typing import Iterable

logger = logging.getLogger("pipeline.lexicon")

_CACHE_DIR_DEFAULT = ".cache/lexicon"
_CACHE_TTL_SEC_DEFAULT = 7 * 24 * 3600

# 한글/영문/숫자 2자 이상 토큰. 이모지·특수기호 제외.
_TOKEN_RE = re.compile(r"[A-Za-z가-힣][A-Za-z0-9가-힣]{1,}")

# Whisper initial_prompt 에 들어가도 유익하지 않은 일반어 (확장 자유).
_STOPWORDS = {
    "진짜","이거","그거","저거","이건","근데","그냥","정말","아니","없다","있다",
    "하다","되다","나서","으로","에서","까지","부터","이랑","라고","라는","하면",
    "해서","뭐야","뭐지","뭐냐","ㅋㅋ","ㅋㅋㅋ","ㅠㅠ","ㄷㄷ","ㅇㅇ","ㅊㅋ","ㅎㅎ",
    "스트리머","스트리밍","방송","채팅","채팅창","시청자","구독자","오늘","어제",
    "지금","이제","여기","저기","거기","그럼","근데","아니면","그리고","그래서",
    "아하","이야","오호","와우","야야","그래","맞아","응","네","예","아니","아뇨",
    "감사","고마워","부탁","안녕","환영","수고","잘자","굿밤","굿모닝",
    "으악","으아","아이고","아이구","으음","어라","어쩔","어머","오마이",
    # 생활 부사/형용사/대명사 (채팅에서 자주 올라와 랭킹을 오염)
    "너무","이게","이걸","많이","그래도","역시","어우","어어","우리","일단",
    "아님","아오","아는데","아무래도","상대","좋은데","좋다","그건","좀","많은",
    "정말","진짜로","약간","완전","대박","레알","헉","헐","에잉","에이","음",
    "어떻게","뭐","왜","어디","언제","누구","이런","저런","그런","어떤","모든",
    "좋아","싫어","같아","같은","같이","같네","같다","보니","보면","보여","보자",
    "이제","저는","저도","나도","내가","내거","제가","저희","우리는","너도","너는",
    "근데요","아니요","네네","으응","응응","나만","나는","나만의",
    # 추가: 30위권에 침투한 일반어/감탄사
    "그게","이미","바로","제발","원래","가자","나이스","역대급","이러면","같은데",
    "처음","마지막","다음","오늘은","오늘도","내일","어제는","계속","점점","갑자기",
    "잠깐","잠시","빨리","천천히","조금","많아","많네","적어","아예","전혀",
    "어차피","결국","드디어","마침내","이번","저번","다른","같다고","아무도","모두",
    "안돼","안됨","됐어","됐다","했어","했다","왔어","왔다","갔어","갔다",
    "보고","보면서","듣고","말고","해주","해줘","해야","하지","하나","둘이",
    "아직","없어","있어","맞음","틀림","무조건","요즘","평소","항상","가끔",
    "있는","없는","있음","없음","있다고","없다고","아닌","맞는","아닌데","맞는데",
    # 게임/방송 일반 영어
    "gg","GG","lol","LOL","ok","OK","vs","VS","the","and","you","for","that","this",
}

# 고유명사 가능성 보너스: 대문자 시작, 겹받침, 외래어 가타가나 등.
_PROPER_HINT_RE = re.compile(r"[A-Z]|ㅉ|ㅆ|ㅃ|ㄸ|ㄲ|[ㄱ-ㅎㅏ-ㅣ]")


def _tokenize(text: str) -> list[str]:
    if not text:
        return []
    return _TOKEN_RE.findall(text)


def _is_likely_proper(token: str) -> bool:
    """짧거나 일반어/stopword 면 False."""
    if len(token) < 2 or len(token) > 20:
        return False
    if token in _STOPWORDS:
        return False
    if token.lower() in _STOPWORDS:
        return False
    # 순수 숫자 제외
    if token.isdigit():
        return False
    return True


def _rank_terms(counter: Counter, limit: int) -> list[str]:
    """빈도순 정렬 후 상위 N개. 동률은 길이 긴 쪽 우선 (보통 더 특이함).

    대소문자만 다른 영문 토큰(`lck` vs `LCK`)은 합산하고 가장 빈도 높은 표기 채택.
    한글은 그대로 유지 (대소문자 개념 없음).
    """
    # 영문 case-fold 합산
    folded: Counter = Counter()
    canonical: dict[str, str] = {}  # lowered -> 가장 빈출 표기
    canonical_count: dict[str, int] = {}
    for t, c in counter.items():
        if not _is_likely_proper(t):
            continue
        is_ascii = t.isascii()
        key = t.lower() if is_ascii else t
        folded[key] += c
        if c > canonical_count.get(key, -1):
            canonical[key] = t
            canonical_count[key] = c
    items = [(canonical[k], folded[k]) for k in folded]
    items.sort(key=lambda tc: (-tc[1], -len(tc[0]), tc[0]))
    return [t for t, _ in items[:limit]]


def _from_chat_log(chat_path: Path) -> Counter:
    counter: Counter = Counter()
    if not chat_path.is_file():
        return counter
    try:
        data = json.loads(chat_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"lexicon: 채팅 로그 읽기 실패 {chat_path}: {e}")
        return counter
    for row in data or []:
        msg = row.get("msg") if isinstance(row, dict) else None
        for tok in _tokenize(msg or ""):
            counter[tok] += 1
    return counter


def _from_community(posts_path: Path) -> Counter:
    counter: Counter = Counter()
    if not posts_path.is_file():
        return counter
    try:
        data = json.loads(posts_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"lexicon: 커뮤니티 파일 읽기 실패 {posts_path}: {e}")
        return counter
    for post in data or []:
        if not isinstance(post, dict):
            continue
        for field in ("title", "body_preview"):
            for tok in _tokenize(post.get(field) or ""):
                # 커뮤니티 표기는 채팅보다 더 정제되어 있으니 가중치 ×2.
                counter[tok] += 2
    return counter


def _from_titles(titles: Iterable[str]) -> Counter:
    counter: Counter = Counter()
    for t in titles:
        for tok in _tokenize(t or ""):
            # 제목은 희소하지만 고유명사 밀도가 높으니 가중치 ×3.
            counter[tok] += 3
    return counter


def _try_namuwiki(channel_name: str, timeout: float = 5.0) -> Counter:
    """나무위키 베스트-에포트 조회. 실패는 조용히 무시."""
    counter: Counter = Counter()
    if not channel_name:
        return counter
    try:
        import urllib.request
        from urllib.parse import quote
        url = f"https://namu.wiki/w/{quote(channel_name)}"
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; auto-caption-generator/1.0)",
            "Accept": "text/html,application/xhtml+xml",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return counter
            raw = resp.read().decode("utf-8", errors="replace")
    except Exception as e:  # noqa: BLE001
        logger.debug(f"lexicon: 나무위키 조회 생략 ({channel_name}): {e}")
        return counter

    # 매우 단순한 태그 스트립 후 토큰화. 나무위키가 막히면 0개 나오는 정상 경로.
    raw = re.sub(r"<script[\s\S]*?</script>", " ", raw, flags=re.I)
    raw = re.sub(r"<style[\s\S]*?</style>", " ", raw, flags=re.I)
    raw = re.sub(r"<[^>]+>", " ", raw)
    for tok in _tokenize(raw):
        counter[tok] += 1
    return counter


def _cache_path(channel_id: str, cache_dir: str | Path) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_\-]", "_", channel_id or "unknown")
    return Path(cache_dir) / f"{safe}.json"


def _load_cache(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _save_cache(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as e:
        logger.warning(f"lexicon: 캐시 쓰기 실패 {path}: {e}")


def build_lexicon(
    channel_id: str,
    channel_name: str = "",
    video_no: str = "",
    vod_title: str = "",
    work_dir: str | Path = "./work",
    extra_titles: Iterable[str] = (),
    limit: int = 30,
    cache_dir: str | Path = _CACHE_DIR_DEFAULT,
    rebuild: bool = False,
    fetch_namuwiki: bool = True,
    cache_ttl_sec: int | None = None,
) -> list[str]:
    """스트리머별 고유명사 후보 리스트를 반환.

    인자:
        channel_id: 캐시 키. 빈 문자열이면 캐시 사용 안 함.
        channel_name: 나무위키 조회 + 기본 포함 단어로 사용.
        video_no: 이번 VOD 의 채팅/커뮤니티 로그를 소스로 쓰기 위한 ID.
        vod_title: 현재 VOD 제목 (토큰 소스).
        work_dir: 과거 VOD 들의 chat/community 를 스캔할 디렉토리.
        extra_titles: 추가로 주입할 제목 목록 (여러 VOD 의 title).
        limit: 반환 단어 수 상한. Whisper prompt 토큰 예산 고려 기본 30.
        rebuild: True 면 캐시 무시 후 재계산.
        fetch_namuwiki: False 면 외부 조회 생략 (CI/airgap).

    반환:
        빈도·가중치 랭킹의 상위 N개 고유명사 후보. 예: ["탬탬버린","케버지","슬더스",...]
    """
    cache_file = _cache_path(channel_id, cache_dir) if channel_id else None
    now = time.time()
    ttl = _CACHE_TTL_SEC_DEFAULT if cache_ttl_sec is None else max(0, int(cache_ttl_sec))
    if cache_file and not rebuild and ttl > 0:
        cached = _load_cache(cache_file)
        if cached and (now - float(cached.get("built_at", 0)) < ttl):
            # 자동 무효화: 캐시 빌드 이후 채팅/커뮤니티 파일이 새로 생기거나
            # 갱신됐으면 신조어가 누락될 수 있으니 재빌드한다 (TTL 보다 강력).
            built_at = float(cached.get("built_at", 0))
            stale = False
            root = Path(work_dir)
            if root.is_dir():
                for sub in root.iterdir():
                    if not sub.is_dir():
                        continue
                    for f in sub.glob("*_chat.log.json"):
                        if f.stat().st_mtime > built_at:
                            stale = True
                            break
                    if stale:
                        break
                    for f in sub.glob("*_community.json"):
                        if f.stat().st_mtime > built_at:
                            stale = True
                            break
                    if stale:
                        break
            if not stale:
                terms = cached.get("terms") or []
                if terms:
                    logger.info(f"lexicon: 캐시 사용 {cache_file.name} ({len(terms)}개, {limit} 요청)")
                    return terms[:limit]
            else:
                logger.info(f"lexicon: 캐시 무효 (신규 chat/community 감지) → 재빌드 {cache_file.name}")

    counter: Counter = Counter()

    # 1) 이번 VOD 채팅/커뮤니티
    if video_no:
        vod_dir = Path(work_dir) / str(video_no)
        counter.update(_from_chat_log(vod_dir / f"{video_no}_chat.log.json"))
        counter.update(_from_community(vod_dir / f"{video_no}_community.json"))

    # 2) 같은 채널의 과거 VOD 들도 쓸 수 있으면 더 좋다.
    if channel_id:
        root = Path(work_dir)
        if root.is_dir():
            for sub in root.iterdir():
                if not sub.is_dir() or sub.name == str(video_no):
                    continue
                # work/<video_no>/<video_no>_chat.log.json 스캔
                for f in sub.glob("*_chat.log.json"):
                    counter.update(_from_chat_log(f))
                for f in sub.glob("*_community.json"):
                    counter.update(_from_community(f))

    # 3) 제목들
    counter.update(_from_titles([vod_title, *extra_titles]))

    # 4) 채널명은 명시적으로 한 번 포함 (랭킹과 별개로).
    terms = _rank_terms(counter, limit=limit * 2)  # 버퍼로 2배 뽑고 아래서 정제
    forced: list[str] = []
    if channel_name:
        forced.append(channel_name.strip())

    # 5) 나무위키 best-effort: 위에서 뽑힌 terms 를 검증 가중치로 쓴다.
    if fetch_namuwiki and channel_name:
        namu = _try_namuwiki(channel_name)
        if namu:
            # 나무위키에 등장하는 단어만 별도 집계해, 위 랭킹 결과와 교집합을 상위로.
            boosted = [t for t in terms if t in namu]
            terms = boosted + [t for t in terms if t not in boosted]

    # 중복 제거 + 상한.
    final: list[str] = []
    seen: set[str] = set()
    for t in [*forced, *terms]:
        if t and t not in seen:
            seen.add(t)
            final.append(t)
        if len(final) >= limit:
            break

    if cache_file:
        _save_cache(cache_file, {
            "built_at": now,
            "channel_id": channel_id,
            "channel_name": channel_name,
            "terms": final,
            "source_video_no": video_no,
        })

    logger.info(f"lexicon: 빌드 완료 channel={channel_id or '?'} terms={len(final)}")
    return final


def format_for_whisper(terms: list[str], prefix: str = "") -> str:
    """Whisper initial_prompt 로 주입할 문자열.

    Whisper prompt 는 ~224 토큰 제약. 한국어 토큰 1~2자당 1 토큰 가량이니
    30개 * 평균 4자 ≈ 120자 → 60~120 토큰 정도로 예산 내.
    """
    if not terms:
        return prefix or ""
    head = prefix or "안녕하세요, 환영합니다. 오늘도 재밌게 해봅시다!"
    # 자연스러운 한국어 문맥에 고유명사를 섞어 Whisper 가 bias 하도록.
    # 너무 많은 쉼표는 오히려 혼란을 주니 문장 하나로 합친다.
    joined = ", ".join(terms)
    return f"{head} 자주 등장하는 표기: {joined}."


def format_for_claude(terms: list[str]) -> str:
    """Claude 프롬프트에 주입할 섹션.

    자막 오인식을 이 목록으로 교정하도록 유도.
    """
    if not terms:
        return ""
    joined = ", ".join(terms)
    return (
        "\n## 알려진 고유명사/신조어 (자막 오인식 교정용)\n"
        f"{joined}\n"
        "자막에서 위 단어들과 발음이 비슷한 표기(예: 비슷한 음절 조합, 받침 차이)가 보이면 "
        "이 표기로 해석/인용하라. 채팅·커뮤니티 원문 표기와 자막이 다르면 채팅·커뮤니티 쪽을 따른다.\n"
    )
