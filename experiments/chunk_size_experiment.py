"""청크 크기별 요약 품질 실험

같은 VOD(캐시된 SRT + 채팅)에 대해 `chunk_max_chars` 를 달리하여
요약을 실행하고, 타임라인 엔트리 개수 / 분당 밀도 / 토큰량을 비교한다.

사용법:
  python -m experiments.chunk_size_experiment

결과:
  experiments/results/chunk_<N>_<timestamp>.md  — 각 구성별 요약 원문
  experiments/results/summary.md                 — 비교 리포트
"""

import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# 프로젝트 루트
_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root))

from pipeline.config import load_config, get_cookies
from pipeline.chat_collector import fetch_all_chats
from pipeline.chat_analyzer import find_edit_points
from pipeline.chunker import chunk_srt
from pipeline.summarizer import process_chunks, merge_results
from pipeline.models import VODInfo
from pipeline.utils import setup_logging

# ───── 실험 대상 ─────
VIDEO_NO = "12702452"
SRT_PATH = _root / "work" / VIDEO_NO / (
    f"{VIDEO_NO}_7시 인생게임 (w. 지누,뿡,똘복) 인생에 프로란 없다. 모두 아마추어다. ٩(●'▿'●)۶_144p_clip1800s.srt"
)
LIMIT_SEC = 1800  # 30분 (캐시된 clip과 일치)

# 테스트할 구성
CONFIGS = [
    {"label": "baseline_150k",  "max_chars": 150000, "overlap_sec": 45},
    {"label": "chunk_15k",      "max_chars": 15000,  "overlap_sec": 30},
    {"label": "chunk_8k",       "max_chars": 8000,   "overlap_sec": 30},
    {"label": "chunk_5k",       "max_chars": 5000,   "overlap_sec": 20},
]

RESULTS_DIR = _root / "experiments" / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def _count_timeline_entries(md: str) -> int:
    """'- **[HH:MM:SS]' 형태 엔트리 카운트"""
    return len(re.findall(r"^\s*-\s*\*\*\s*\[\d{2}:\d{2}:\d{2}\]", md, flags=re.M))


def _count_highlight_entries(md: str) -> int:
    return len(re.findall(r"^\s*\d+\.\s*\*\*\[\d{2}:\d{2}:\d{2}", md, flags=re.M))


def _detect_sections(md: str) -> dict:
    return {
        "has_hashtags": bool(re.search(r"#\S+.*#\S+.*#\S+", md)),
        "has_pullquote": bool(re.search(r'^\s*>\s*".+"', md, flags=re.M)),
        "has_editor_notes": bool(re.search(r"에디터.*후기|방송 후기", md)),
        "char_count": len(md),
        "line_count": md.count("\n"),
    }


def run_experiment(cfg: dict, vod: VODInfo, chats, highlights, timeout: int = 300) -> dict:
    logger = logging.getLogger("pipeline")
    logger.info("=" * 60)
    logger.info(f"실험: {cfg['label']} (max_chars={cfg['max_chars']}, overlap={cfg['overlap_sec']}s)")
    logger.info("=" * 60)

    t0 = time.time()

    # 청크 생성
    chunks = chunk_srt(str(SRT_PATH), max_chars=cfg["max_chars"], overlap_sec=cfg["overlap_sec"])
    chunk_count = len(chunks)
    total_chars = sum(c["char_count"] for c in chunks)
    logger.info(f"  청크: {chunk_count}개, 총 {total_chars:,}자")

    # 청크별 분석 (Claude CLI)
    chunk_t0 = time.time()
    chunk_results = process_chunks(chunks, highlights, chats, vod, claude_timeout=timeout)
    chunk_elapsed = time.time() - chunk_t0

    # 통합 요약
    merge_t0 = time.time()
    summary = merge_results(chunk_results, vod, [], highlights, claude_timeout=timeout)
    merge_elapsed = time.time() - merge_t0

    elapsed = time.time() - t0

    # 결과 저장
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = RESULTS_DIR / f"{cfg['label']}_{ts}.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(summary)

    metrics = {
        "label": cfg["label"],
        "max_chars": cfg["max_chars"],
        "overlap_sec": cfg["overlap_sec"],
        "chunk_count": chunk_count,
        "total_chunk_chars": total_chars,
        "summary_chars": len(summary),
        "timeline_entries": _count_timeline_entries(summary),
        "highlight_entries": _count_highlight_entries(summary),
        "entries_per_min": round(_count_timeline_entries(summary) / (LIMIT_SEC / 60), 2),
        "chunk_phase_sec": round(chunk_elapsed, 1),
        "merge_phase_sec": round(merge_elapsed, 1),
        "total_sec": round(elapsed, 1),
        "output_path": str(out_path),
        **_detect_sections(summary),
    }
    logger.info(f"  ✓ 완료: {elapsed:.1f}s | 타임라인 {metrics['timeline_entries']}개 ({metrics['entries_per_min']}/분)")
    return metrics


def main():
    log_dir = _root / "output" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = setup_logging(str(log_dir))

    if not SRT_PATH.exists():
        logger.error(f"SRT 파일 없음: {SRT_PATH}")
        sys.exit(1)

    cfg = load_config()
    cookies = get_cookies(cfg)

    # VOD 메타데이터 재조회
    from content.network import NetworkManager
    logger.info(f"VOD {VIDEO_NO} 메타데이터 조회 중...")
    _, _, _, _, _, metadata = NetworkManager.get_video_info(VIDEO_NO, cookies)
    vod = VODInfo(
        video_no=VIDEO_NO,
        title=metadata.get("title", ""),
        channel_id=cfg["target_channel_id"],
        channel_name=metadata.get("channelName", ""),
        duration=metadata.get("duration", 0),
        publish_date=metadata.get("createdDate", ""),
        category=metadata.get("category", ""),
    )

    # 채팅 수집 (30분 제한)
    logger.info("채팅 수집 중 (30분 제한)...")
    chats = fetch_all_chats(VIDEO_NO, max_duration_sec=LIMIT_SEC)
    logger.info(f"  채팅 {len(chats):,}개")

    # 하이라이트 분석
    highlights = find_edit_points(chats) if chats else []
    logger.info(f"  하이라이트 {len(highlights)}개")

    # 각 구성 실행
    results = []
    for conf in CONFIGS:
        try:
            m = run_experiment(conf, vod, chats, highlights)
            results.append(m)
        except Exception as e:
            logger.error(f"실험 실패 ({conf['label']}): {e}")
            results.append({"label": conf["label"], "error": str(e)})

    # 비교 리포트 저장
    summary_path = RESULTS_DIR / "summary.md"
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("# Chunk Size Experiment Results\n\n")
        f.write(f"- VOD: `{VIDEO_NO}` / 제한 {LIMIT_SEC}초\n")
        f.write(f"- SRT: {SRT_PATH.name}\n")
        f.write(f"- 실행 시각: {datetime.now().isoformat()}\n\n")

        f.write("## 비교표\n\n")
        f.write("| 구성 | 청크수 | 타임라인 | 분당 밀도 | 하이라이트 | 요약자수 | 총 소요 |\n")
        f.write("|---|---|---|---|---|---|---|\n")
        for r in results:
            if "error" in r:
                f.write(f"| {r['label']} | ❌ {r['error'][:40]} |||||\n")
                continue
            f.write(
                f"| {r['label']} | {r['chunk_count']} | {r['timeline_entries']} | "
                f"{r['entries_per_min']}/분 | {r['highlight_entries']} | "
                f"{r['summary_chars']:,} | {r['total_sec']}s |\n"
            )

        f.write("\n## 전체 메트릭 (JSON)\n\n```json\n")
        f.write(json.dumps(results, ensure_ascii=False, indent=2))
        f.write("\n```\n")

    logger.info(f"\n실험 완료. 비교 리포트: {summary_path}")
    for r in results:
        if "error" not in r:
            logger.info(
                f"  [{r['label']:20s}] 청크 {r['chunk_count']}개 → "
                f"타임라인 {r['timeline_entries']}개 ({r['entries_per_min']}/분) "
                f"/ {r['total_sec']}s"
            )


if __name__ == "__main__":
    main()
