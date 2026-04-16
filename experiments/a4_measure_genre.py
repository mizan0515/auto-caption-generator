"""A4 genre-acquisition measurement wrapper.

Wraps experiments/a4_measure.py's measure_cell + evaluate_global on a new cells
file (experiments/_a4_cells_genre.json) and writes a NEW raw JSON at
experiments/results/2026-04-16_phase-a4_genre-acquisition_raw.json.

Does NOT overwrite experiments/results/2026-04-15_phase-a4_raw.json.
"""
from __future__ import annotations

import json
import logging
import sys
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

CELLS_FILE = Path("experiments/_a4_cells_genre.json")
RESULT_JSON = Path("experiments/results/2026-04-16_phase-a4_genre-acquisition_raw.json")


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
    for cell in cells:
        print(f"[genre-measure] cell={cell['sample_id']}", flush=True)
        rows, cell_summary = measure_cell(cell, encoder, capture, template_hash)
        all_rows.extend(rows)
        cell_summaries.append(cell_summary)

    global_summary = evaluate_global(cell_summaries, template_hash)
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
