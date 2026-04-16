"""A4 acquisition-followup measurement wrapper.

Reads experiments/_a4_cells_followup.json (chat-fed W4f + W5f), runs measure_cell +
evaluate_global from a4_measure, writes NEW raw JSON at
experiments/results/2026-04-16_phase-a4-acquisition-followup_raw.json.

Does NOT overwrite:
  - experiments/results/2026-04-15_phase-a4_raw.json
  - experiments/results/2026-04-16_phase-a4_genre-acquisition_raw.json

Corrected-protocol note: both cells are chat-fed (~50-80 msgs/min), so retry-collapse
risk from the 2026-04-16 no-chat run should be reduced. We additionally sleep 360s
between cells to let the Anthropic prompt cache (5-min TTL) expire cleanly before a
new cell primes a fresh cache.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(name)s %(levelname)s %(message)s")

import tiktoken

from experiments.a4_measure import (
    ENCODING_NAME,
    UsageCaptureHandler,
    evaluate_global,
    make_template_hash,
    measure_cell,
)

CELLS_FILE = Path("experiments/_a4_cells_followup.json")
RESULT_JSON = Path("experiments/results/2026-04-16_phase-a4-acquisition-followup_raw.json")
INTER_CELL_IDLE_SEC = 360  # prompt-cache TTL + margin


def main() -> int:
    cells = json.loads(CELLS_FILE.read_text(encoding="utf-8"))
    if not cells:
        print("No cells found.", flush=True)
        return 1

    encoder = tiktoken.get_encoding(ENCODING_NAME)
    capture = UsageCaptureHandler()
    logging.getLogger("pipeline").addHandler(capture)
    template_hash = make_template_hash()

    all_rows = []
    cell_summaries = []
    for i, cell in enumerate(cells):
        print(f"[followup-measure] cell={cell['sample_id']} "
              f"platform_category={cell.get('platform_category')} "
              f"content_judgement={cell.get('content_judgement')}", flush=True)
        rows, cell_summary = measure_cell(cell, encoder, capture, template_hash)
        # carry the schema fields explicitly into every row and cell
        for r in rows:
            r["platform_category"] = cell.get("platform_category")
            r["content_judgement"] = cell.get("content_judgement")
            r["chat_coverage"] = cell.get("chat_coverage", "full")
        cell_summary["platform_category"] = cell.get("platform_category")
        cell_summary["content_judgement"] = cell.get("content_judgement")
        cell_summary["chat_coverage"] = cell.get("chat_coverage", "full")
        all_rows.extend(rows)
        cell_summaries.append(cell_summary)
        if i + 1 < len(cells):
            print(f"[followup-measure] inter-cell idle {INTER_CELL_IDLE_SEC}s "
                  "(prompt-cache TTL clearance)", flush=True)
            time.sleep(INTER_CELL_IDLE_SEC)

    global_summary = evaluate_global(cell_summaries, template_hash)
    # annotate labeling schema
    global_summary["labeling_schema"] = {
        "primary": "platform_category",
        "secondary": "content_judgement",
        "promotion_axis_uses": "platform_category",
    }
    payload = {
        "rows": all_rows,
        "cells": cell_summaries,
        "global": global_summary,
    }
    RESULT_JSON.parent.mkdir(parents=True, exist_ok=True)
    RESULT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {RESULT_JSON}", flush=True)
    print(json.dumps(global_summary, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
