"""SRT → LLM 청크 분할 (srt-chunk.py 로직 재사용)

분할 단위 (Phase A2):
    split_by_chars() 와 split_by_tokens() 모두 per-cue `Cue.raw_block` 를
    계량 단위로 사용한다. raw_block 은 인덱스 라인 + "HH:MM:SS,ms --> ..." 타임스탬프
    라인 + 텍스트 라인들 + 빈 줄을 포함하는 **원본 SRT 블록** 이다.
    cues_to_txt() 의 출력("[HH:MM:SS] text")은 보고용 요약이며 분할 단위가 아니다.
    두 단위는 대략 ~2x 차이가 나므로 (raw_block > cues_to_txt) 동일 임계값을 공유하지 않는다.
    이 불변식은 Phase A2 C3/C4 의 전제이므로 변경 시 experiments/results 와 동기화한다.
"""

import json
import logging
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

# 프로젝트 루트를 sys.path에 추가
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

logger = logging.getLogger("pipeline")

# srt-chunk.py의 핵심 로직을 인라인으로 가져옴 (파일명에 하이픈이 있어 import 불가)
SRT_TS_RE = re.compile(r"(?P<h>\d{2}):(?P<m>\d{2}):(?P<s>\d{2}),(?P<ms>\d{3})")
TIME_LINE_RE = re.compile(r"^\s*(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})")


@dataclass
class Cue:
    start_ms: int
    end_ms: int
    start_ts: str
    end_ts: str
    text_lines: List[str]
    raw_block: str


def _ts_to_ms(ts: str) -> int:
    m = SRT_TS_RE.match(ts.strip())
    if not m:
        raise ValueError(f"Invalid timestamp: {ts}")
    h, mi, s, ms = int(m.group("h")), int(m.group("m")), int(m.group("s")), int(m.group("ms"))
    return (((h * 60 + mi) * 60) + s) * 1000 + ms


def _ms_to_hhmmss(ms: int) -> str:
    sec = ms // 1000
    h = sec // 3600
    sec %= 3600
    m = sec // 60
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def parse_srt(path: str) -> List[Cue]:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    blocks = re.split(r"\n{2,}", content.strip(), flags=re.MULTILINE)
    cues: List[Cue] = []

    for b in blocks:
        lines = [ln.rstrip("\n") for ln in b.splitlines()]
        if len(lines) < 2:
            continue
        time_i = None
        for i, ln in enumerate(lines[:6]):
            if TIME_LINE_RE.match(ln):
                time_i = i
                break
        if time_i is None:
            continue
        m = TIME_LINE_RE.match(lines[time_i])
        start_ts, end_ts = m.group(1), m.group(2)
        cues.append(Cue(
            start_ms=_ts_to_ms(start_ts), end_ms=_ts_to_ms(end_ts),
            start_ts=start_ts, end_ts=end_ts,
            text_lines=lines[time_i + 1:],
            raw_block="\n".join(lines) + "\n\n",
        ))

    cues.sort(key=lambda c: (c.start_ms, c.end_ms))
    return cues


def cues_to_txt(cues: List[Cue]) -> str:
    out = []
    for c in cues:
        t = _ms_to_hhmmss(c.start_ms)
        text = " ".join(ln.strip() for ln in c.text_lines if ln.strip())
        if text:
            out.append(f"[{t}] {text}")
    return "\n".join(out).rstrip() + "\n"


def split_by_chars(cues: List[Cue], max_chars: int, overlap_sec: int) -> List[List[Cue]]:
    overlap_ms = overlap_sec * 1000
    chunks: List[List[Cue]] = []
    i, n = 0, len(cues)

    while i < n:
        start_i = i
        char_count = 0
        j = i
        while j < n:
            blk_len = len(cues[j].raw_block)
            if j > i and char_count + blk_len > max_chars:
                break
            char_count += blk_len
            j += 1

        chunks.append(cues[i:j])

        if j < n and overlap_ms > 0:
            next_start_ms = cues[j].start_ms
            rewind_ms = max(0, next_start_ms - overlap_ms)
            k = j
            while k > start_i and cues[k - 1].start_ms >= rewind_ms:
                k -= 1
            next_i = k
        else:
            next_i = j

        if next_i <= i:
            next_i = i + 1
        i = next_i

    return chunks


_TOKEN_ENCODERS: dict = {}


def _get_token_encoder(encoding_name: str):
    """tiktoken 인코더를 lazy 로드. 동일 인코딩은 프로세스 단위로 캐시."""
    cached = _TOKEN_ENCODERS.get(encoding_name)
    if cached is not None:
        return cached
    try:
        import tiktoken
    except ImportError as e:
        raise RuntimeError(
            "chunk_max_tokens 를 사용하려면 tiktoken 이 필요합니다. "
            "`pip install tiktoken` 후 재시도하세요."
        ) from e
    encoder = tiktoken.get_encoding(encoding_name)
    _TOKEN_ENCODERS[encoding_name] = encoder
    return encoder


def split_by_tokens(
    cues: List[Cue],
    max_tokens: int,
    overlap_sec: int,
    encoding_name: str = "cl100k_base",
) -> List[List[Cue]]:
    """token 기반 분할. split_by_chars() 와 동일한 overlap rewind 규칙.

    계량 단위는 per-cue raw_block 의 tiktoken 토큰 수이다 (docstring 참조).
    """
    encoder = _get_token_encoder(encoding_name)
    overlap_ms = overlap_sec * 1000
    chunks: List[List[Cue]] = []
    i, n = 0, len(cues)

    # 동일 cue 에 대한 토큰 수를 여러 번 계산하지 않도록 캐시.
    token_count_cache: List[int] = [len(encoder.encode(c.raw_block)) for c in cues]

    while i < n:
        start_i = i
        token_count = 0
        j = i
        while j < n:
            blk_tokens = token_count_cache[j]
            if j > i and token_count + blk_tokens > max_tokens:
                break
            token_count += blk_tokens
            j += 1

        chunks.append(cues[i:j])

        if j < n and overlap_ms > 0:
            next_start_ms = cues[j].start_ms
            rewind_ms = max(0, next_start_ms - overlap_ms)
            k = j
            while k > start_i and cues[k - 1].start_ms >= rewind_ms:
                k -= 1
            next_i = k
        else:
            next_i = j

        if next_i <= i:
            next_i = i + 1
        i = next_i

    return chunks


def chunk_srt(
    srt_path: str,
    max_chars: int = 150000,
    overlap_sec: int = 45,
    max_tokens: Optional[int] = None,
    tokenizer_encoding: str = "cl100k_base",
) -> list[dict]:
    """
    SRT 파일을 청크로 분할.
    반환: [{"index": 1, "start_ms": ..., "end_ms": ..., "text": "..."}, ...]

    precedence (Phase A2):
        max_tokens 가 None 이 아니면 split_by_tokens() 사용 (토큰 기준).
        None 이면 max_chars 로 split_by_chars() 사용 (글자 기준, 레거시).
    두 경로 모두 per-cue raw_block 을 계량 단위로 삼는다.
    """
    if max_tokens is not None:
        logger.info(
            f"SRT 청크 분할: {srt_path} "
            f"(max_tokens={max_tokens}, encoding={tokenizer_encoding}, overlap={overlap_sec}s)"
        )
    else:
        logger.info(f"SRT 청크 분할: {srt_path} (max_chars={max_chars}, overlap={overlap_sec}s)")

    cues = parse_srt(srt_path)
    if not cues:
        logger.warning("SRT에 자막이 없습니다.")
        return []

    if max_tokens is not None:
        chunks = split_by_tokens(cues, max_tokens, overlap_sec, tokenizer_encoding)
    else:
        chunks = split_by_chars(cues, max_chars, overlap_sec)
    result = []

    for idx, chunk_cues in enumerate(chunks, 1):
        if not chunk_cues:
            continue
        start_ms = chunk_cues[0].start_ms
        end_ms = max(c.end_ms for c in chunk_cues)
        text = cues_to_txt(chunk_cues)
        result.append({
            "index": idx,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "start_hhmmss": _ms_to_hhmmss(start_ms),
            "end_hhmmss": _ms_to_hhmmss(end_ms),
            "cue_count": len(chunk_cues),
            "char_count": len(text),
            "text": text,
        })

    logger.info(f"  {len(result)}개 청크 생성 (총 {len(cues)}개 자막)")
    return result
