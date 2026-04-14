"""A4 execute skeleton for multi-cell margin/generalization measurement.

This script is intentionally created in Turn 4 without executing any model call.
Populate CELLS in Turn 5 before running:

    python -X utf8 experiments/a4_measure.py

The implementation mirrors A3's cold/warm paired-call protocol while extending
the raw JSON schema to cell-level and global-level aggregation.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import sys
import time
from pathlib import Path
from typing import Any

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Allow running directly from repo root without PYTHONPATH gymnastics
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(name)s %(levelname)s %(message)s")

import tiktoken

from pipeline.chat_analyzer import find_edit_points
from pipeline.chunker import chunk_srt
from pipeline.claude_cli import call_claude
from pipeline.models import VODInfo
from pipeline.summarizer import _build_chunk_prompt


RESULT_JSON = Path("experiments/results/2026-04-15_phase-a4_raw.json")
ENCODING_NAME = "cl100k_base"
MAX_TOKENS = 2500
OVERLAP_SEC = 30
TIMEOUT_SEC = 300
CONSISTENCY_TOLERANCE = 0.03
# Turn 5 cost cap: sample first N chunks per cell (2 calls each). Set to 0 to disable cap.
# Rationale: n_valid_chunks >= 3 is the per-cell sufficiency threshold from C4, so 4 is enough
# headroom to survive one consistency failure while keeping the per-cell cost bounded
# (~$2.5 total for 3 cells at ~$0.1/call).
MAX_CHUNKS_PER_CELL = 4

CHAT_LINE_RE = re.compile(r"^\[(\d{2}):(\d{2}):(\d{2})\]\s*([^:]+?):\s*(.*)$")
USAGE_RE = re.compile(
    r"Claude usage "
    r"input_tokens=(?P<input>\d+) "
    r"output_tokens=(?P<output>\d+) "
    r"cache_creation_input_tokens=(?P<cc>\d+) "
    r"cache_read_input_tokens=(?P<cr>\d+)"
    r"(?:\s+session_id=(?P<sid>\S+))?"
    r"(?:\s+total_cost_usd=(?P<cost>[\d.]+))?"
)

# Turn 5 (claude-code execute): CELLS loaded from experiments/_a4_cells.json at runtime
# to keep Unicode paths out of Python source. See _a4_cells.json for exact live values.
_CELLS_JSON = Path("experiments/_a4_cells.json")
if _CELLS_JSON.exists():
    CELLS: list[dict[str, Any]] = json.loads(_CELLS_JSON.read_text(encoding="utf-8"))
else:
    CELLS: list[dict[str, Any]] = []


def parse_chats(path: Path) -> list[dict[str, Any]]:
    chats: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            match = CHAT_LINE_RE.match(line.rstrip("\n"))
            if not match:
                continue
            hh, mm, ss, nick, msg = match.groups()
            sec = (int(hh) * 60 + int(mm)) * 60 + int(ss)
            chats.append({"ms": sec * 1000, "nick": nick.strip(), "msg": msg.strip()})
    return chats


def filter_chats(chats: list[dict[str, Any]], start_sec: int, end_sec: int) -> list[dict[str, Any]]:
    start_ms = start_sec * 1000
    end_ms = end_sec * 1000
    return [chat for chat in chats if start_ms <= int(chat["ms"]) < end_ms]


def density_from_window(chats: list[dict[str, Any]], window_sec: int) -> float:
    if window_sec <= 0:
        return 0.0
    return len(chats) / (window_sec / 60.0)


def density_tier(density_msgs_per_min: float) -> str:
    if density_msgs_per_min <= 20:
        return "low"
    if density_msgs_per_min <= 60:
        return "medium"
    return "high"


def small_n_median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    n = len(ordered)
    if n % 2 == 1:
        return ordered[n // 2]
    return (ordered[n // 2 - 1] + ordered[n // 2]) / 2.0


def small_n_p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = max(0, int(round(0.95 * (len(ordered) - 1))))
    return ordered[idx]


def make_template_hash() -> str:
    dummy_chunk = {
        "index": 0,
        "start_ms": 0,
        "end_ms": 30000,
        "start_hhmmss": "00:00:00",
        "end_hhmmss": "00:00:30",
        "cue_count": 0,
        "char_count": 0,
        "text": "__TRANSCRIPT__",
    }
    dummy_vod = VODInfo(
        video_no="0",
        title="template-hash-probe",
        channel_id="0",
        channel_name="0",
        duration=30,
        publish_date="1970-01-01",
    )
    prompt = _build_chunk_prompt(dummy_chunk, [], [], dummy_vod)
    prefix = prompt.split("__TRANSCRIPT__", 1)[0]
    return hashlib.sha256(prefix.encode("utf-8")).hexdigest()[:16]


class UsageCaptureHandler(logging.Handler):
    """Capture the most recent 'Claude usage' log emission."""

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.last: dict[str, Any] | None = None

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        match = USAGE_RE.search(message)
        if not match:
            return
        self.last = {
            "input_tokens": int(match.group("input")),
            "output_tokens": int(match.group("output")),
            "cache_creation_input_tokens": int(match.group("cc")),
            "cache_read_input_tokens": int(match.group("cr")),
            "session_id": match.group("sid"),
            "total_cost_usd": float(match.group("cost")) if match.group("cost") else None,
        }


def run_once(prompt: str, capture: UsageCaptureHandler, timeout: int = TIMEOUT_SEC) -> dict[str, Any]:
    capture.last = None
    t0 = time.time()
    result = call_claude(prompt, timeout=timeout)
    dt = time.time() - t0
    if capture.last is None:
        raise RuntimeError("No 'Claude usage' log line captured for this call.")
    usage = dict(capture.last)
    usage["wall_sec"] = round(dt, 2)
    usage["result_len"] = len(result) if isinstance(result, str) else 0
    return usage


def normalize_cell(cell: dict[str, Any]) -> dict[str, Any]:
    required = {
        "sample_id",
        "srt_path",
        "chat_log_path",
        "length_min",
        "genre",
        "density_tier",
        "chat_density_msgs_per_min",
    }
    missing = sorted(required - set(cell))
    if missing:
        raise ValueError(f"Cell is missing required keys: {missing}")
    return dict(cell)


def measure_cell(
    cell: dict[str, Any],
    encoder: Any,
    capture: UsageCaptureHandler,
    template_hash: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cell = normalize_cell(cell)
    srt_path = Path(str(cell["srt_path"]))
    chat_log_path = Path(str(cell["chat_log_path"]))
    chats_all = parse_chats(chat_log_path)
    window_sec = int(cell["length_min"]) * 60
    chats = filter_chats(chats_all, 0, window_sec)
    computed_density = round(density_from_window(chats, window_sec), 4)

    if cell.get("chat_density_msgs_per_min") is None:
        cell["chat_density_msgs_per_min"] = computed_density
    if not cell.get("density_tier"):
        cell["density_tier"] = density_tier(float(cell["chat_density_msgs_per_min"]))

    highlights = find_edit_points(chats)
    vod = VODInfo(
        video_no=str(cell.get("video_no", cell["sample_id"])),
        title=str(cell.get("title", cell["sample_id"])),
        channel_id=str(cell.get("channel_id", "unknown")),
        channel_name=str(cell.get("channel_name", "unknown")),
        duration=int(cell.get("duration_sec", window_sec)),
        publish_date=str(cell.get("publish_date", "1970-01-01")),
    )

    chunks = chunk_srt(
        str(srt_path),
        max_chars=150000,
        overlap_sec=OVERLAP_SEC,
        max_tokens=MAX_TOKENS,
        tokenizer_encoding=ENCODING_NAME,
    )
    total_chunks_full = len(chunks)
    if MAX_CHUNKS_PER_CELL and len(chunks) > MAX_CHUNKS_PER_CELL:
        chunks = chunks[:MAX_CHUNKS_PER_CELL]

    rows: list[dict[str, Any]] = []
    for chunk in chunks:
        prompt = _build_chunk_prompt(chunk, highlights, chats, vod)
        predicted = len(encoder.encode(prompt))

        cold = run_once(prompt, capture)
        time.sleep(2)
        warm = run_once(prompt, capture)

        user_attributable = cold["input_tokens"] + cold["cache_creation_input_tokens"]
        cache_read_delta = warm["cache_read_input_tokens"] - cold["cache_read_input_tokens"]
        deviation = abs(cache_read_delta - user_attributable)
        tolerance = user_attributable * CONSISTENCY_TOLERANCE
        consistency_pass = deviation <= tolerance

        retry = None
        if not consistency_pass:
            time.sleep(5)
            retry_cold = run_once(prompt, capture)
            time.sleep(2)
            retry_warm = run_once(prompt, capture)
            retry_user_attributable = retry_cold["input_tokens"] + retry_cold["cache_creation_input_tokens"]
            retry_cache_read_delta = retry_warm["cache_read_input_tokens"] - retry_cold["cache_read_input_tokens"]
            retry_deviation = abs(retry_cache_read_delta - retry_user_attributable)
            retry_tolerance = retry_user_attributable * CONSISTENCY_TOLERANCE
            consistency_pass = retry_deviation <= retry_tolerance
            retry = {
                "cold": retry_cold,
                "warm": retry_warm,
                "user_attributable": retry_user_attributable,
                "cache_read_delta": retry_cache_read_delta,
                "deviation": retry_deviation,
                "tolerance": round(retry_tolerance, 2),
            }
            if consistency_pass:
                cold = retry_cold
                warm = retry_warm
                user_attributable = retry_user_attributable
                cache_read_delta = retry_cache_read_delta
                deviation = retry_deviation
                tolerance = retry_tolerance

        row = {
            "sample_id": cell["sample_id"],
            "length_min": int(cell["length_min"]),
            "genre": str(cell["genre"]),
            "density_tier": str(cell["density_tier"]),
            "chat_density_msgs_per_min": float(cell["chat_density_msgs_per_min"]),
            "chunk_index": int(chunk["index"]),
            "predicted": int(predicted),
            "input": int(cold["input_tokens"]),
            "cache_creation": int(cold["cache_creation_input_tokens"]),
            "cache_read": int(cold["cache_read_input_tokens"]),
            "user_attributable": int(user_attributable),
            "cache_read_delta": int(cache_read_delta),
            "consistency_pass": bool(consistency_pass),
            "user_ratio": round(user_attributable / predicted, 4) if predicted else None,
            "additive_overhead": int(user_attributable - predicted),
            "template_hash": template_hash,
            "cold": cold,
            "warm": warm,
            "deviation": int(deviation),
            "tolerance": round(tolerance, 2),
            "retry": retry,
        }
        rows.append(row)

    valid_rows = [row for row in rows if row["consistency_pass"]]
    ratio_values = [float(row["user_ratio"]) for row in valid_rows if row["user_ratio"] is not None]
    additive_values = [int(row["additive_overhead"]) for row in valid_rows]
    cell_summary = {
        "sample_id": cell["sample_id"],
        "length_min": int(cell["length_min"]),
        "genre": str(cell["genre"]),
        "density_tier": str(cell["density_tier"]),
        "chat_density_msgs_per_min": float(cell["chat_density_msgs_per_min"]),
        "n_chunks": len(rows),
        "n_chunks_full_cell": int(total_chunks_full),
        "n_chunks_cap": int(MAX_CHUNKS_PER_CELL) if MAX_CHUNKS_PER_CELL else 0,
        "n_valid_chunks": len(valid_rows),
        "median_user_ratio": round(small_n_median(ratio_values), 4) if ratio_values else None,
        "P95_user_ratio": round(small_n_p95(ratio_values), 4) if ratio_values else None,
        "median_additive_overhead": round(small_n_median([float(v) for v in additive_values]), 2) if additive_values else None,
        "insufficient_data": len(valid_rows) < 3,
        "computed_chat_density_msgs_per_min": computed_density,
    }
    return rows, cell_summary


def evaluate_global(cell_summaries: list[dict[str, Any]], template_hash: str) -> dict[str, Any]:
    covered = [cell for cell in cell_summaries if not cell["insufficient_data"]]
    covered_p95s = [float(cell["P95_user_ratio"]) for cell in covered if cell["P95_user_ratio"] is not None]
    global_median_p95 = small_n_median(covered_p95s)

    min_allowed = global_median_p95 * 0.85 if global_median_p95 is not None else None
    max_allowed = global_median_p95 * 1.15 if global_median_p95 is not None else None
    dispersion_failures = []
    for cell in covered:
        cell_p95 = cell["P95_user_ratio"]
        if cell_p95 is None or min_allowed is None or max_allowed is None:
            continue
        if not (min_allowed <= float(cell_p95) <= max_allowed):
            dispersion_failures.append(cell["sample_id"])

    lengths = sorted({int(cell["length_min"]) for cell in covered})
    genres = sorted({str(cell["genre"]) for cell in covered})
    density_tiers = sorted({str(cell["density_tier"]) for cell in covered})
    axis_coverage_ok = (
        len(covered) >= 5
        and {30, 60, 180}.issubset(set(lengths))
        and len(genres) >= 2
        and len(density_tiers) >= 2
    )
    dispersion_ok = len(dispersion_failures) == 0 and global_median_p95 is not None

    if axis_coverage_ok and dispersion_ok:
        decision = "global_multiplicative"
    elif len(covered) >= 5 and len(genres) >= 2 and len(density_tiers) >= 2:
        decision = "global_additive"
    elif covered:
        decision = "per_cell_multiplicative"
    else:
        decision = "scope_blocked"

    recommended_margin = None
    if decision == "global_multiplicative" and global_median_p95 is not None:
        recommended_margin = math.ceil(max(covered_p95s) * 1.05 * 100) / 100

    return {
        "template_hash": template_hash,
        "covered_cell_count": len(covered),
        "covered_lengths_min": lengths,
        "covered_genres": genres,
        "covered_density_tiers": density_tiers,
        "global_median_P95": round(global_median_p95, 4) if global_median_p95 is not None else None,
        "dispersion_range": [round(min_allowed, 4), round(max_allowed, 4)] if min_allowed is not None else None,
        "dispersion_failures": dispersion_failures,
        "axis_coverage_ok": axis_coverage_ok,
        "dispersion_ok": dispersion_ok,
        "decision": decision,
        "recommended_margin": recommended_margin,
    }


def main() -> int:
    if not CELLS:
        print("Populate CELLS in Turn 5 before running this script.")
        return 1

    encoder = tiktoken.get_encoding(ENCODING_NAME)
    capture = UsageCaptureHandler()
    logging.getLogger("pipeline").addHandler(capture)
    template_hash = make_template_hash()

    all_rows: list[dict[str, Any]] = []
    cell_summaries: list[dict[str, Any]] = []
    for raw_cell in CELLS:
        rows, cell_summary = measure_cell(raw_cell, encoder, capture, template_hash)
        all_rows.extend(rows)
        cell_summaries.append(cell_summary)

    global_summary = evaluate_global(cell_summaries, template_hash)
    payload = {
        "rows": all_rows,
        "cells": cell_summaries,
        "global": global_summary,
    }
    RESULT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {RESULT_JSON}")
    print(json.dumps(global_summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
