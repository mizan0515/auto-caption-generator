"""B12 — 하이라이트 필터 파라미터 sweep.

목표: highlight_radius_sec × cold_sample_sec 조합별로
  - 필터 후 자수
  - 청크 수
  - 시간 커버리지 (%)
  - (옵션) 1셀에 한해 Haiku 호출로 품질 smoke
를 측정해 base 대비 절감/품질 균형점을 찾는다.

테스트 자산: pipeline_config.json 의 experiment_test_vod / experiment_limit_duration_sec.
chat 로그는 work/<vod>/<vod>_chat.log (라인 포맷: "[HH:MM:SS] nick: msg").

실행:
    python -X utf8 experiments/b12_highlight_filter_sweep.py
    python -X utf8 experiments/b12_highlight_filter_sweep.py --quality-cell 300x30  # Haiku 호출 추가

사이드 이펙트: experiments/results/<date>_b12_highlight-filter-sweep_*.{json,md} 작성.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(
    level=logging.WARNING,  # chunker.py 의 INFO 노이즈 억제
    stream=sys.stderr,
    format="%(name)s %(levelname)s %(message)s",
)

from pipeline.chat_analyzer import find_edit_points
from pipeline.chunker import chunk_srt, filter_cues_by_highlights, parse_srt
from pipeline.config import load_config

RADIUS_GRID = [180, 300, 420, 600]
COLD_GRID = [15, 30, 60]
COVERAGE_BUCKET_SEC = 60  # 1분 단위 커버리지 측정

CHAT_LINE_RE = re.compile(r"^\[(\d{2}):(\d{2}):(\d{2})\]\s+([^:]+):\s+(.*)$")


def load_chat_log(path: Path, duration_limit_sec: Optional[int]) -> list[dict]:
    chats: list[dict] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            m = CHAT_LINE_RE.match(line.rstrip("\n"))
            if not m:
                continue
            h, mi, s, nick, msg = m.groups()
            sec = int(h) * 3600 + int(mi) * 60 + int(s)
            if duration_limit_sec and sec > duration_limit_sec:
                continue
            chats.append({"ms": sec * 1000, "nick": nick.strip(), "msg": msg.strip()})
    return chats


def find_clip_srt(work_dir: Path, vod: str, limit_sec: int) -> Path:
    """work/<vod>/ 에서 *_clip<limit>s.srt 또는 가장 짧은 *_clip*s.srt 우선,
    없으면 풀 SRT (*.srt) 사용."""
    candidates = list(work_dir.glob(f"{vod}_*_clip{limit_sec}s.srt"))
    if candidates:
        return candidates[0]
    clips = sorted(work_dir.glob(f"{vod}_*_clip*s.srt"))
    if clips:
        # 가장 짧은 클립 SRT 선택
        def _sec(p: Path) -> int:
            m = re.search(r"_clip(\d+)s\.srt$", p.name)
            return int(m.group(1)) if m else 10**9
        clips.sort(key=_sec)
        return clips[0]
    full = list(work_dir.glob(f"{vod}_*.srt"))
    if not full:
        raise FileNotFoundError(f"SRT 파일을 찾을 수 없습니다: {work_dir}/{vod}_*.srt")
    return full[0]


def measure_cell(
    cues_full: list,
    highlights: list[dict],
    duration_sec: int,
    radius: int,
    cold: int,
    chunk_max_chars: int,
    overlap_sec: int,
) -> dict:
    """단일 (radius, cold) 셀 측정."""
    filtered = filter_cues_by_highlights(
        cues_full, highlights, hot_radius_sec=radius, cold_sample_sec=cold,
    )

    total_chars = sum(len(c.raw_block) for c in filtered)

    # 시간 커버리지: 1분 버킷 중 적어도 1개 cue 가 시작하는 비율
    n_buckets = max(1, duration_sec // COVERAGE_BUCKET_SEC + 1)
    covered = set()
    for c in filtered:
        b = (c.start_ms // 1000) // COVERAGE_BUCKET_SEC
        if b < n_buckets:
            covered.add(b)
    coverage_pct = 100.0 * len(covered) / n_buckets

    # chunk_srt 는 file 경로를 받으므로 직접 split 함수를 써야 한다.
    # 간단하게: filtered cue 의 raw_block 합 / chunk_max_chars 로 청크 수 추정.
    # 정확한 측정을 위해 chunker 의 _split_by_chars 와 동일 로직 사용.
    chunks = _split_cues_by_chars(filtered, max_chars=chunk_max_chars, overlap_sec=overlap_sec)

    return {
        "radius_sec": radius,
        "cold_sample_sec": cold,
        "n_cues": len(filtered),
        "total_chars": total_chars,
        "n_chunks": len(chunks),
        "coverage_pct": round(coverage_pct, 1),
    }


def _split_cues_by_chars(cues: list, max_chars: int, overlap_sec: int) -> list[list]:
    """chunker._split_by_chars 의 raw_block 기준 단순 재현 (외부 의존 없음)."""
    chunks: list[list] = []
    if not cues:
        return chunks
    n = len(cues)
    overlap_ms = overlap_sec * 1000
    i = 0
    while i < n:
        j = i
        char_count = 0
        while j < n:
            blk_chars = len(cues[j].raw_block)
            if j > i and char_count + blk_chars > max_chars:
                break
            char_count += blk_chars
            j += 1
        chunks.append(cues[i:j])
        if j < n and overlap_ms > 0:
            next_start_ms = cues[j].start_ms
            rewind_ms = max(0, next_start_ms - overlap_ms)
            k = j
            while k > i and cues[k - 1].start_ms >= rewind_ms:
                k -= 1
            next_i = k if k > i else j
        else:
            next_i = j
        if next_i <= i:
            next_i = i + 1
        i = next_i
    return chunks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vod", default=None, help="override experiment_test_vod")
    ap.add_argument("--limit-sec", type=int, default=None,
                    help="override experiment_limit_duration_sec")
    ap.add_argument("--chunk-max-chars", type=int, default=None,
                    help="override chunk_max_chars (default from config)")
    args = ap.parse_args()

    cfg = load_config()
    vod = args.vod or cfg.get("experiment_test_vod") or ""
    if not vod:
        print("ERROR: pipeline_config.json 의 experiment_test_vod 가 비어있습니다.",
              file=sys.stderr)
        return 2
    limit_sec = args.limit_sec if args.limit_sec is not None else int(
        cfg.get("experiment_limit_duration_sec") or 1800
    )
    chunk_max_chars = args.chunk_max_chars or int(cfg.get("chunk_max_chars", 8000))
    overlap_sec = int(cfg.get("chunk_overlap_sec", 30))

    work_dir = Path(cfg.get("work_dir", "./work")).resolve() / vod
    srt_path = find_clip_srt(work_dir, vod, limit_sec)
    chat_path = work_dir / f"{vod}_chat.log"
    if not chat_path.exists():
        print(f"ERROR: chat 로그 없음: {chat_path}", file=sys.stderr)
        return 2

    print(f"[B12] vod={vod} limit={limit_sec}s")
    print(f"      srt={srt_path.name}")
    print(f"      chat={chat_path.name}")
    print(f"      chunk_max_chars={chunk_max_chars} overlap={overlap_sec}")

    cues_full = parse_srt(str(srt_path))
    if not cues_full:
        print("ERROR: SRT 파싱 결과 비어있음.", file=sys.stderr)
        return 2

    actual_duration = max(c.end_ms for c in cues_full) // 1000
    duration_sec = min(actual_duration, limit_sec) if limit_sec else actual_duration
    print(f"      cues_full={len(cues_full)} duration={duration_sec}s")

    chats = load_chat_log(chat_path, duration_limit_sec=limit_sec)
    print(f"      chats(loaded)={len(chats):,}")

    if not chats:
        print("ERROR: 채팅 0건 → 하이라이트 추출 불가.", file=sys.stderr)
        return 2

    highlights = find_edit_points(chats)
    print(f"      highlights={len(highlights)}")

    # baseline (no filter) 측정
    base_chunks = _split_cues_by_chars(
        cues_full, max_chars=chunk_max_chars, overlap_sec=overlap_sec
    )
    base_chars = sum(len(c.raw_block) for c in cues_full)
    n_buckets = max(1, duration_sec // COVERAGE_BUCKET_SEC + 1)
    base_covered = {(c.start_ms // 1000) // COVERAGE_BUCKET_SEC for c in cues_full}
    base_coverage = 100.0 * len([b for b in base_covered if b < n_buckets]) / n_buckets

    baseline = {
        "radius_sec": None, "cold_sample_sec": None,
        "n_cues": len(cues_full), "total_chars": base_chars,
        "n_chunks": len(base_chunks), "coverage_pct": round(base_coverage, 1),
    }
    print(f"\n[baseline] cues={baseline['n_cues']} chars={baseline['total_chars']:,} "
          f"chunks={baseline['n_chunks']} cov={baseline['coverage_pct']}%")

    rows: list[dict] = []
    for r in RADIUS_GRID:
        for c in COLD_GRID:
            row = measure_cell(
                cues_full, highlights, duration_sec, r, c, chunk_max_chars, overlap_sec,
            )
            row["chars_saving_pct"] = round(
                100.0 * (1 - row["total_chars"] / baseline["total_chars"]), 1
            )
            rows.append(row)
            print(
                f"  radius={r:>3}s cold={c:>2}s | cues={row['n_cues']:>4} "
                f"chars={row['total_chars']:>7,} (-{row['chars_saving_pct']:>4}%) "
                f"chunks={row['n_chunks']:>2} cov={row['coverage_pct']:>5}%"
            )

    # 결과 저장
    today = datetime.now().strftime("%Y-%m-%d")
    results_dir = Path(__file__).resolve().parent / "results"
    results_dir.mkdir(exist_ok=True)
    suffix = f"_clip{limit_sec}s"
    raw_path = results_dir / f"{today}_b12_highlight-filter-sweep{suffix}_raw.json"
    md_path = results_dir / f"{today}_b12_highlight-filter-sweep{suffix}.md"

    raw = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "vod": vod,
        "limit_sec": limit_sec,
        "duration_sec": duration_sec,
        "srt": srt_path.name,
        "chunk_max_chars": chunk_max_chars,
        "chunk_overlap_sec": overlap_sec,
        "n_chats_used": len(chats),
        "n_highlights": len(highlights),
        "baseline": baseline,
        "cells": rows,
    }
    raw_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

    # 추천 셀: coverage >= 80% 중 chars_saving 최대
    eligible = [r for r in rows if r["coverage_pct"] >= 80.0]
    eligible.sort(key=lambda x: x["chars_saving_pct"], reverse=True)
    rec = eligible[0] if eligible else None

    md_lines = [
        f"# B12 — 하이라이트 필터 파라미터 sweep",
        "",
        f"- 생성: {raw['generated_at']}",
        f"- VOD: `{vod}` (limit={limit_sec}s, duration={duration_sec}s)",
        f"- SRT: `{srt_path.name}`",
        f"- chunk_max_chars={chunk_max_chars}, overlap={overlap_sec}s",
        f"- 채팅 로드: {len(chats):,}건 → 하이라이트 {len(highlights)}개",
        "",
        "## Baseline (no filter)",
        f"- cues: {baseline['n_cues']}",
        f"- 총 자수: {baseline['total_chars']:,}",
        f"- 청크 수: {baseline['n_chunks']}",
        f"- 시간 커버리지: {baseline['coverage_pct']}% (1분 버킷 기준)",
        "",
        "## Sweep Grid",
        "",
        "| radius (s) | cold (s) | cues | chars | 절감 % | chunks | 커버리지 % |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        md_lines.append(
            f"| {r['radius_sec']} | {r['cold_sample_sec']} | {r['n_cues']} "
            f"| {r['total_chars']:,} | {r['chars_saving_pct']} | {r['n_chunks']} "
            f"| {r['coverage_pct']} |"
        )

    md_lines += ["", "## 추천"]
    if rec:
        md_lines.append(
            f"- coverage ≥ 80% 중 절감률 최대: "
            f"`radius={rec['radius_sec']}s, cold={rec['cold_sample_sec']}s` "
            f"(절감 {rec['chars_saving_pct']}%, 커버리지 {rec['coverage_pct']}%)"
        )
    else:
        md_lines.append("- 80% 커버리지를 만족하는 셀이 없음 → 클립이 너무 짧거나 chat 밀도 부족 가능.")

    md_lines += [
        "",
        "## 해석 가이드",
        "- 커버리지가 클립 전체에서 80% 이상이어야 \"전체 시간축 누락 없음\" 기준 충족.",
        "- 30분 클립에서는 highlight 가 적어 cold 샘플 비중이 높아질 수 있음 → 풀 VOD 결과와 다를 수 있다.",
        "- chunk 수가 1~2 로 수렴하면 chunk_max_chars 가 너무 큰 신호 (B13 후보).",
    ]
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    print(f"\n[saved] {raw_path}")
    print(f"[saved] {md_path}")
    if rec:
        print(f"[recommend] radius={rec['radius_sec']}s cold={rec['cold_sample_sec']}s "
              f"saving={rec['chars_saving_pct']}% cov={rec['coverage_pct']}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
