"""B13 — chunk_max_chars 최적화 sweep.

목표: chunk_max_chars 후보 [15000, 20000, 30000, 50000] 에 대해
  - 청크 수
  - 청크당 평균/최대 자수
  - 청크당 평균/최대 분 (시간 길이)
  - 단일 청크 호출 시 timeout 위험도 (자수 기반 추정)
  - (옵션) B12 추천 필터(radius=180, cold=60) 적용 vs 미적용 비교
를 측정해 throughput/타임아웃 균형점을 찾는다.

테스트 자산: pipeline_config.json 의 experiment_test_vod / experiment_limit_duration_sec.

실행:
    python -X utf8 experiments/b13_chunk_max_chars_sweep.py
    python -X utf8 experiments/b13_chunk_max_chars_sweep.py --limit-sec 10800
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
    level=logging.WARNING,
    stream=sys.stderr,
    format="%(name)s %(levelname)s %(message)s",
)

from pipeline.chat_analyzer import find_edit_points
from pipeline.chunker import filter_cues_by_highlights, parse_srt
from pipeline.config import load_config

CHUNK_GRID = [15000, 20000, 30000, 50000]
# B12 추천 (3h 클립 기준 70% 절감 + 98% 커버리지)
B12_RECOMMENDED_RADIUS = 180
B12_RECOMMENDED_COLD = 60

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
    candidates = list(work_dir.glob(f"{vod}_*_clip{limit_sec}s.srt"))
    if candidates:
        return candidates[0]
    clips = sorted(work_dir.glob(f"{vod}_*_clip*s.srt"))
    if clips:
        def _sec(p: Path) -> int:
            m = re.search(r"_clip(\d+)s\.srt$", p.name)
            return int(m.group(1)) if m else 10**9
        clips.sort(key=_sec)
        return clips[0]
    full = list(work_dir.glob(f"{vod}_*.srt"))
    if not full:
        raise FileNotFoundError(f"SRT 파일을 찾을 수 없습니다: {work_dir}/{vod}_*.srt")
    return full[0]


def _split_cues_by_chars(cues: list, max_chars: int, overlap_sec: int) -> list[list]:
    """chunker._split_by_chars 의 raw_block 기준 단순 재현."""
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


def _summarize_chunks(chunks: list[list]) -> dict:
    if not chunks:
        return {
            "n_chunks": 0, "chars_avg": 0, "chars_max": 0,
            "minutes_avg": 0.0, "minutes_max": 0.0,
        }
    chars = [sum(len(c.raw_block) for c in ch) for ch in chunks]
    spans_sec = [
        max(0, (ch[-1].end_ms - ch[0].start_ms) / 1000) if ch else 0
        for ch in chunks
    ]
    return {
        "n_chunks": len(chunks),
        "chars_avg": round(sum(chars) / len(chars)),
        "chars_max": max(chars),
        "minutes_avg": round(sum(spans_sec) / len(spans_sec) / 60, 1),
        "minutes_max": round(max(spans_sec) / 60, 1),
    }


def _timeout_risk(chars_max: int) -> str:
    """rough heuristic: 한국어 8K chars ≈ 5K token, claude_timeout_sec=300 기준."""
    if chars_max < 20000:
        return "low"
    if chars_max < 40000:
        return "medium"
    if chars_max < 80000:
        return "high"
    return "very-high"


def measure_grid(label: str, cues: list, overlap_sec: int) -> list[dict]:
    rows: list[dict] = []
    for max_chars in CHUNK_GRID:
        chunks = _split_cues_by_chars(cues, max_chars=max_chars, overlap_sec=overlap_sec)
        s = _summarize_chunks(chunks)
        s["chunk_max_chars"] = max_chars
        s["timeout_risk"] = _timeout_risk(s["chars_max"])
        rows.append(s)
        print(
            f"  [{label:>10}] max={max_chars:>5} | chunks={s['n_chunks']:>2} "
            f"avg={s['chars_avg']:>6,}/{s['minutes_avg']:>4}min "
            f"max={s['chars_max']:>6,}/{s['minutes_max']:>4}min "
            f"risk={s['timeout_risk']}"
        )
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vod", default=None)
    ap.add_argument("--limit-sec", type=int, default=None)
    args = ap.parse_args()

    cfg = load_config()
    vod = args.vod or cfg.get("experiment_test_vod") or ""
    if not vod:
        print("ERROR: experiment_test_vod 비어있음.", file=sys.stderr)
        return 2
    limit_sec = args.limit_sec if args.limit_sec is not None else int(
        cfg.get("experiment_limit_duration_sec") or 1800
    )
    overlap_sec = int(cfg.get("chunk_overlap_sec", 30))

    work_dir = Path(cfg.get("work_dir", "./work")).resolve() / vod
    srt_path = find_clip_srt(work_dir, vod, limit_sec)
    chat_path = work_dir / f"{vod}_chat.log"
    if not chat_path.exists():
        print(f"ERROR: chat 로그 없음: {chat_path}", file=sys.stderr)
        return 2

    print(f"[B13] vod={vod} limit={limit_sec}s overlap={overlap_sec}")
    print(f"      srt={srt_path.name}")

    cues_full = parse_srt(str(srt_path))
    if not cues_full:
        print("ERROR: SRT 파싱 0건.", file=sys.stderr)
        return 2

    actual_duration = max(c.end_ms for c in cues_full) // 1000
    duration_sec = min(actual_duration, limit_sec) if limit_sec else actual_duration
    total_chars_full = sum(len(c.raw_block) for c in cues_full)
    print(f"      cues_full={len(cues_full)} duration={duration_sec}s "
          f"total_chars={total_chars_full:,}")

    chats = load_chat_log(chat_path, duration_limit_sec=limit_sec)
    print(f"      chats={len(chats):,}")
    highlights = find_edit_points(chats) if chats else []
    print(f"      highlights={len(highlights)}")

    cues_filtered = filter_cues_by_highlights(
        cues_full, highlights,
        hot_radius_sec=B12_RECOMMENDED_RADIUS,
        cold_sample_sec=B12_RECOMMENDED_COLD,
    ) if highlights else cues_full
    total_chars_filtered = sum(len(c.raw_block) for c in cues_filtered)
    print(f"      filtered (B12 추천: r={B12_RECOMMENDED_RADIUS}s c={B12_RECOMMENDED_COLD}s): "
          f"{len(cues_filtered)} cues, {total_chars_filtered:,} chars")

    print("\n== sweep: filter OFF ==")
    rows_off = measure_grid("filter:off", cues_full, overlap_sec)
    print("\n== sweep: filter ON (B12 추천) ==")
    rows_on = measure_grid("filter:on ", cues_filtered, overlap_sec)

    today = datetime.now().strftime("%Y-%m-%d")
    results_dir = Path(__file__).resolve().parent / "results"
    results_dir.mkdir(exist_ok=True)
    suffix = f"_clip{limit_sec}s"
    raw_path = results_dir / f"{today}_b13_chunk-max-chars-sweep{suffix}_raw.json"
    md_path = results_dir / f"{today}_b13_chunk-max-chars-sweep{suffix}.md"

    raw = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "vod": vod,
        "limit_sec": limit_sec,
        "duration_sec": duration_sec,
        "srt": srt_path.name,
        "overlap_sec": overlap_sec,
        "n_chats": len(chats),
        "n_highlights": len(highlights),
        "filter_off": {
            "n_cues": len(cues_full),
            "total_chars": total_chars_full,
            "cells": rows_off,
        },
        "filter_on_b12": {
            "radius_sec": B12_RECOMMENDED_RADIUS,
            "cold_sample_sec": B12_RECOMMENDED_COLD,
            "n_cues": len(cues_filtered),
            "total_chars": total_chars_filtered,
            "cells": rows_on,
        },
        "timeout_risk_thresholds_chars_max": {
            "low": "< 20000", "medium": "< 40000",
            "high": "< 80000", "very-high": ">= 80000",
        },
    }
    raw_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

    # 추천: filter:on 그리드에서 risk=low 우선 → 그 안에서 청크 수 최소 → chunk_max_chars 최소
    risk_order = {"low": 0, "medium": 1, "high": 2, "very-high": 3}
    eligible = [r for r in rows_on if r["timeout_risk"] in ("low", "medium")]
    eligible.sort(key=lambda r: (
        risk_order[r["timeout_risk"]], r["n_chunks"], r["chunk_max_chars"]
    ))
    rec = eligible[0] if eligible else None

    md = [
        "# B13 — chunk_max_chars 최적화 sweep",
        "",
        f"- 생성: {raw['generated_at']}",
        f"- VOD: `{vod}` (limit={limit_sec}s, duration={duration_sec}s)",
        f"- SRT: `{srt_path.name}`, overlap={overlap_sec}s",
        f"- 채팅: {len(chats):,}건 → 하이라이트 {len(highlights)}개",
        "",
        "## Filter OFF (raw cues)",
        f"- cues={len(cues_full)}, total_chars={total_chars_full:,}",
        "",
        "| chunk_max_chars | chunks | chars(평균/최대) | 분(평균/최대) | timeout risk |",
        "|---:|---:|---|---|---|",
    ]
    for r in rows_off:
        md.append(
            f"| {r['chunk_max_chars']:,} | {r['n_chunks']} "
            f"| {r['chars_avg']:,} / {r['chars_max']:,} "
            f"| {r['minutes_avg']} / {r['minutes_max']} | {r['timeout_risk']} |"
        )

    md += [
        "",
        f"## Filter ON (B12 추천: radius={B12_RECOMMENDED_RADIUS}s, cold={B12_RECOMMENDED_COLD}s)",
        f"- cues={len(cues_filtered)}, total_chars={total_chars_filtered:,}",
        "",
        "| chunk_max_chars | chunks | chars(평균/최대) | 분(평균/최대) | timeout risk |",
        "|---:|---:|---|---|---|",
    ]
    for r in rows_on:
        md.append(
            f"| {r['chunk_max_chars']:,} | {r['n_chunks']} "
            f"| {r['chars_avg']:,} / {r['chars_max']:,} "
            f"| {r['minutes_avg']} / {r['minutes_max']} | {r['timeout_risk']} |"
        )

    md += ["", "## 추천"]
    if rec:
        md.append(
            f"- filter ON 그리드에서 timeout 위험 medium 이하 + 청크 수 최소: "
            f"`chunk_max_chars={rec['chunk_max_chars']:,}` "
            f"(chunks={rec['n_chunks']}, max={rec['chars_max']:,} chars, risk={rec['timeout_risk']})"
        )
    else:
        md.append("- 모든 셀이 high risk → filter 강도를 더 올리거나 chunk_max_chars 후보를 낮춰야 함.")

    md += [
        "",
        "## 해석 가이드",
        "- timeout_risk 는 chars_max 기준 휴리스틱 (한국어 ~1.6 chars/token, claude_timeout_sec=300).",
        "- 실제 Haiku/Sonnet 호출 검증은 후속 (cost 우려로 sweep 단계 제외).",
        f"- 30분 클립은 total_chars 가 작아 chunk_max_chars 영향 미미. 풀 VOD 검증 권장.",
    ]
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")

    print(f"\n[saved] {raw_path}")
    print(f"[saved] {md_path}")
    if rec:
        print(f"[recommend] chunk_max_chars={rec['chunk_max_chars']:,} "
              f"chunks={rec['n_chunks']} risk={rec['timeout_risk']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
