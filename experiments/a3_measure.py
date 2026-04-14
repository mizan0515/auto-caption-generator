"""A3 Turn 5 execute — cold/warm paired measurements on work/12702452 single sample.

Outputs JSON with per-chunk cold/warm usage + predicted tokens. The result MD is
written separately by the orchestration turn so this script stays narrowly-scoped.

Invocation:
    python -X utf8 experiments/a3_measure.py

Code changes to pipeline/* are forbidden by the A3 contract. This script only reads
public functions (chunk_srt, _build_chunk_prompt, find_edit_points, call_claude)
and does not modify any pipeline module.
"""

import glob
import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# Force UTF-8 on Windows stdout
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Capture pipeline INFO so _log_usage output is parsable by this script.
logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(name)s %(levelname)s %(message)s")

import tiktoken

from pipeline.chunker import chunk_srt
from pipeline.summarizer import _build_chunk_prompt
from pipeline.chat_analyzer import find_edit_points
from pipeline.claude_cli import call_claude
from pipeline.models import VODInfo


WORK_DIR = Path("work/12702452")
SRT_PATH = glob.glob(str(WORK_DIR / "*clip1800s.srt"))[0]
CHAT_PATH = WORK_DIR / "12702452_chat.log"
RESULT_JSON = Path("experiments/results/2026-04-15_phase-a3_raw.json")

CHAT_LINE_RE = re.compile(r"^\[(\d{2}):(\d{2}):(\d{2})\]\s*([^:]+?):\s*(.*)$")


def parse_chats(path: Path) -> list[dict]:
    chats = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            m = CHAT_LINE_RE.match(line.rstrip("\n"))
            if not m:
                continue
            h, mi, s, nick, msg = m.groups()
            ms = ((int(h) * 60 + int(mi)) * 60 + int(s)) * 1000
            chats.append({"ms": ms, "nick": nick.strip(), "msg": msg.strip()})
    return chats


# Parse the 'Claude usage ...' INFO line emitted by pipeline.claude_cli._log_usage.
USAGE_RE = re.compile(
    r"Claude usage "
    r"input_tokens=(?P<input>\d+) "
    r"output_tokens=(?P<output>\d+) "
    r"cache_creation_input_tokens=(?P<cc>\d+) "
    r"cache_read_input_tokens=(?P<cr>\d+)"
    r"(?:\s+session_id=(?P<sid>\S+))?"
    r"(?:\s+total_cost_usd=(?P<cost>[\d.]+))?"
)


class UsageCaptureHandler(logging.Handler):
    """Capture the most recent 'Claude usage' log emission."""
    def __init__(self):
        super().__init__(level=logging.INFO)
        self.last = None

    def emit(self, record: logging.LogRecord):
        msg = record.getMessage()
        m = USAGE_RE.search(msg)
        if m:
            self.last = {
                "input_tokens": int(m.group("input")),
                "output_tokens": int(m.group("output")),
                "cache_creation_input_tokens": int(m.group("cc")),
                "cache_read_input_tokens": int(m.group("cr")),
                "session_id": m.group("sid"),
                "total_cost_usd": float(m.group("cost")) if m.group("cost") else None,
            }


def run_once(prompt: str, capture: UsageCaptureHandler, timeout: int = 300) -> dict:
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


def main() -> int:
    print(f"SRT: {SRT_PATH}")
    print(f"CHAT: {CHAT_PATH}")

    # 1. Chunks (max_tokens=2500, overlap=30, max_chars=150000 so char gate never fires)
    chunks = chunk_srt(SRT_PATH, max_chars=150000, overlap_sec=30, max_tokens=2500)
    print(f"chunks: {len(chunks)}")
    assert len(chunks) == 5, f"expected 5 chunks, got {len(chunks)}"

    # 2. Chats + highlights
    chats = parse_chats(CHAT_PATH)
    print(f"chats: {len(chats)}")
    highlights = find_edit_points(chats)
    print(f"highlights: {len(highlights)}")

    # 3. chat density (msgs/min)
    if chats:
        duration_min = max(c["ms"] for c in chats) / 60000.0
        density = len(chats) / duration_min if duration_min else 0.0
    else:
        density = 0.0
    print(f"chat_density_msgs_per_min: {density:.2f}")

    # 4. VOD info (use work/ metadata for title; channel fields can be placeholder)
    vod = VODInfo(
        video_no="12702452",
        title="7시 인생게임 (w. 지누,뿡,똘복) 인생에 프로란 없다. 모두 아마추어다.",
        channel_id="a7e175625fdea5a7d98428302b7aa57f",
        channel_name="탬탬버린",
        duration=1800,
        publish_date="2026-04-12",
    )

    # 5. Tokenizer + usage capture wiring
    enc = tiktoken.get_encoding("cl100k_base")
    capture = UsageCaptureHandler()
    logging.getLogger("pipeline").addHandler(capture)

    rows = []
    for chunk in chunks:
        prompt = _build_chunk_prompt(chunk, highlights, chats, vod)
        predicted = len(enc.encode(prompt))
        row = {
            "chunk_index": chunk["index"],
            "start_hhmmss": chunk["start_hhmmss"],
            "end_hhmmss": chunk["end_hhmmss"],
            "cue_count": chunk["cue_count"],
            "char_count": chunk["char_count"],
            "prompt_chars": len(prompt),
            "predicted_prompt_tokens": predicted,
            "cold": None,
            "warm": None,
            "retry_cold": None,
            "retry_warm": None,
            "consistency_fail": False,
            "user_attributable_cold": None,
            "cache_read_delta": None,
            "user_ratio": None,
        }

        print(f"\n=== chunk {chunk['index']} predicted={predicted} prompt_chars={len(prompt)} ===")

        # Cold run (allow timeout errors to surface). Keep warm within 5 min.
        row["cold"] = run_once(prompt, capture)
        print(f"  cold: {row['cold']}")
        time.sleep(2)  # small pause; still within 5 min cache window
        row["warm"] = run_once(prompt, capture)
        print(f"  warm: {row['warm']}")

        ua_cold = row["cold"]["input_tokens"] + row["cold"]["cache_creation_input_tokens"]
        cr_delta = row["warm"]["cache_read_input_tokens"] - row["cold"]["cache_read_input_tokens"]
        row["user_attributable_cold"] = ua_cold
        row["cache_read_delta"] = cr_delta
        row["user_ratio"] = round(ua_cold / predicted, 4) if predicted else None

        tolerance = ua_cold * 0.03
        deviation = abs(cr_delta - ua_cold)
        row["deviation"] = deviation
        row["tolerance"] = round(tolerance, 2)
        if deviation > tolerance:
            print(f"  ⚠ consistency deviation {deviation} > tolerance {tolerance:.2f}; retrying once...")
            time.sleep(5)
            row["retry_cold"] = run_once(prompt, capture)
            time.sleep(2)
            row["retry_warm"] = run_once(prompt, capture)
            ua2 = row["retry_cold"]["input_tokens"] + row["retry_cold"]["cache_creation_input_tokens"]
            cr2 = row["retry_warm"]["cache_read_input_tokens"] - row["retry_cold"]["cache_read_input_tokens"]
            dev2 = abs(cr2 - ua2)
            tol2 = ua2 * 0.03
            row["retry_deviation"] = dev2
            row["retry_tolerance"] = round(tol2, 2)
            if dev2 > tol2:
                row["consistency_fail"] = True
                print(f"  ✗ consistency-fail after retry: dev={dev2} tol={tol2:.2f}")
            else:
                # Use retry as authoritative
                row["user_attributable_cold"] = ua2
                row["cache_read_delta"] = cr2
                row["user_ratio"] = round(ua2 / predicted, 4) if predicted else None
                print(f"  ✓ retry passed: ua={ua2} user_ratio={row['user_ratio']}")
        else:
            print(f"  ✓ consistency OK: dev={deviation} tol={tolerance:.2f} user_ratio={row['user_ratio']}")

        rows.append(row)

    # Aggregate
    valid = [r for r in rows if not r["consistency_fail"]]
    ratios = sorted(r["user_ratio"] for r in valid if r["user_ratio"] is not None)
    n = len(ratios)
    if n:
        median = ratios[n // 2] if n % 2 else (ratios[n // 2 - 1] + ratios[n // 2]) / 2
        # P95 — for small n, use the max as P95 per contract's note
        p95_idx = max(0, int(round(0.95 * (n - 1))))
        p95 = ratios[p95_idx]
    else:
        median = p95 = None

    import math
    if p95 is not None:
        recommended_margin = math.ceil(p95 * 1.05 * 100) / 100
    else:
        recommended_margin = None

    summary = {
        "n_chunks_total": len(rows),
        "n_chunks_valid": len(valid),
        "consistency_fail_count": sum(1 for r in rows if r["consistency_fail"]),
        "ratios_sorted": ratios,
        "sample_median_user_ratio": median,
        "global_p95_user_ratio": p95,
        "recommended_margin": recommended_margin,
        "chat_density_msgs_per_min": round(density, 2),
        "sample_scope": "30-min Korean talk (w. 지누/뿡/똘복), chat_density ≈ {:.2f} msgs/min".format(density),
    }

    out = {"rows": rows, "summary": summary}
    RESULT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nWrote:", RESULT_JSON)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
