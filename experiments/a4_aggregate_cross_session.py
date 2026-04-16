"""Deterministic cross-session aggregation over A4 raw artifacts.

Reads three raw JSONs from experiments/results/:
  - 2026-04-15_phase-a4_raw.json                       (W1, W2, W3)
  - 2026-04-16_phase-a4_genre-acquisition_raw.json     (W4-offset1800s-game-nochat, W5-11688000-30min-olympics-nochat)
  - 2026-04-16_phase-a4-acquisition-followup_raw.json  (W4f-offset1800s-12702452-chat, W5f-11688000-30min-chat)

Feeds their per-cell summaries into a single evaluate_global pass and writes:
  - experiments/results/2026-04-16_phase-a4_cross-session-aggregation_raw.json
  - experiments/results/2026-04-16_phase-a4_cross-session-aggregation.md

Constraints:
  - No edit to source raw JSONs.
  - No pipeline code edit.
  - No pipeline_config.json mutation.
  - platform_category is authoritative axis label per acquisition-followup schema fix.
    Cells lacking platform_category are counted in covered_cell_count via genre/insufficient_data,
    but excluded from platform_category distinct-count (marked "unlabeled").
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "experiments" / "results"

SOURCES = [
    RESULTS_DIR / "2026-04-15_phase-a4_raw.json",
    RESULTS_DIR / "2026-04-16_phase-a4_genre-acquisition_raw.json",
    RESULTS_DIR / "2026-04-16_phase-a4-acquisition-followup_raw.json",
]

OUT_JSON = RESULTS_DIR / "2026-04-16_phase-a4_cross-session-aggregation_raw.json"
OUT_MD = RESULTS_DIR / "2026-04-16_phase-a4_cross-session-aggregation.md"


def load_evaluate_global():
    spec = importlib.util.spec_from_file_location(
        "_a4_measure_mod", ROOT / "experiments" / "a4_measure.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.evaluate_global


def main() -> int:
    evaluate_global = load_evaluate_global()

    source_cells: list[tuple[str, dict[str, Any]]] = []
    template_hashes: set[str] = set()
    for src in SOURCES:
        data = json.loads(src.read_text(encoding="utf-8"))
        th = data.get("global", {}).get("template_hash")
        if th:
            template_hashes.add(th)
        for cell in data.get("cells", []):
            source_cells.append((src.name, cell))

    if len(template_hashes) != 1:
        print(f"WARN: template_hash mismatch across sources: {template_hashes}", file=sys.stderr)
    template_hash = next(iter(template_hashes)) if template_hashes else ""

    merged_cells = [cell for _, cell in source_cells]

    global_summary = evaluate_global(merged_cells, template_hash)

    covered_cells = [cell for cell in merged_cells if not cell.get("insufficient_data")]
    platform_categories = sorted(
        {
            cell.get("platform_category")
            for cell in covered_cells
            if cell.get("platform_category")
        }
    )
    covered_platform_category_count = len(platform_categories)
    unlabeled_covered = [
        cell["sample_id"] for cell in covered_cells if not cell.get("platform_category")
    ]

    promotion_ready = (
        global_summary["covered_cell_count"] >= 5
        and covered_platform_category_count >= 2
        and len(global_summary["covered_density_tiers"]) >= 2
        and global_summary["dispersion_ok"]
    )

    labeling_schema_block = {
        "primary": "platform_category",
        "secondary": "content_judgement",
        "promotion_axis_uses": "platform_category",
        "note": "Cells lacking platform_category are counted in evaluate_global via genre/insufficient_data "
        "but excluded from platform_category distinct-count reported here.",
    }

    payload = {
        "source_files": [src.name for src in SOURCES],
        "merged_cells": merged_cells,
        "global": global_summary,
        "labeling_schema": labeling_schema_block,
        "platform_category_coverage": {
            "covered_platform_categories": platform_categories,
            "covered_platform_category_count": covered_platform_category_count,
            "unlabeled_covered_sample_ids": unlabeled_covered,
        },
        "promotion_readiness": {
            "ready": promotion_ready,
            "gate": "covered_cell_count>=5 AND covered_platform_category>=2 AND covered_density_tiers>=2 AND dispersion_ok",
            "covered_cell_count": global_summary["covered_cell_count"],
            "covered_platform_category_count": covered_platform_category_count,
            "covered_density_tiers_count": len(global_summary["covered_density_tiers"]),
            "dispersion_ok": global_summary["dispersion_ok"],
        },
    }

    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines: list[str] = []
    lines.append("# A4 Cross-Session Aggregation")
    lines.append("")
    lines.append("Deterministic aggregation across three raw artifacts:")
    for src in SOURCES:
        lines.append(f"- `{src.name}`")
    lines.append("")
    lines.append("## Labeling schema")
    lines.append("")
    lines.append(
        "`platform_category` (from Chzzk `videoCategoryValue`) is the authoritative axis label. "
        "`content_judgement` is an optional annotation. "
        "`promotion_axis_uses=platform_category`."
    )
    lines.append("")
    lines.append("## Merged cells")
    lines.append("")
    lines.append(
        "| sample_id | length_min | genre | density_tier | platform_category | insufficient_data | median_user_ratio | P95_user_ratio |"
    )
    lines.append("|---|---|---|---|---|---|---|---|")
    for cell in merged_cells:
        lines.append(
            "| {sid} | {lm} | {gn} | {dt} | {pc} | {insu} | {med} | {p95} |".format(
                sid=cell.get("sample_id", ""),
                lm=cell.get("length_min", ""),
                gn=cell.get("genre", ""),
                dt=cell.get("density_tier", ""),
                pc=cell.get("platform_category") or "(unlabeled)",
                insu=cell.get("insufficient_data"),
                med=cell.get("median_user_ratio"),
                p95=cell.get("P95_user_ratio"),
            )
        )
    lines.append("")
    lines.append("## Global aggregation")
    lines.append("")
    lines.append(f"- template_hash: `{global_summary['template_hash']}`")
    lines.append(f"- covered_cell_count: **{global_summary['covered_cell_count']}**")
    lines.append(f"- covered_lengths_min: {global_summary['covered_lengths_min']}")
    lines.append(f"- covered_genres: {global_summary['covered_genres']}")
    lines.append(f"- covered_density_tiers: {global_summary['covered_density_tiers']}")
    lines.append(
        f"- covered_platform_categories: {platform_categories} (count={covered_platform_category_count})"
    )
    if unlabeled_covered:
        lines.append(f"- unlabeled_covered_sample_ids: {unlabeled_covered}")
    lines.append(f"- global_median_P95: {global_summary['global_median_P95']}")
    lines.append(f"- dispersion_range: {global_summary['dispersion_range']}")
    lines.append(f"- dispersion_failures: {global_summary['dispersion_failures']}")
    lines.append(f"- axis_coverage_ok: {global_summary['axis_coverage_ok']}")
    lines.append(f"- dispersion_ok: {global_summary['dispersion_ok']}")
    lines.append(f"- decision: **{global_summary['decision']}**")
    lines.append(f"- recommended_margin: {global_summary['recommended_margin']}")
    lines.append("")
    lines.append("## Promotion readiness")
    lines.append("")
    lines.append(
        "Gate: `covered_cell_count>=5 AND covered_platform_category>=2 AND covered_density_tiers>=2 AND dispersion_ok`"
    )
    lines.append("")
    lines.append(
        f"- covered_cell_count: {global_summary['covered_cell_count']} "
        f"({'>=5 PASS' if global_summary['covered_cell_count'] >= 5 else '<5 FAIL'})"
    )
    lines.append(
        f"- covered_platform_category_count: {covered_platform_category_count} "
        f"({'>=2 PASS' if covered_platform_category_count >= 2 else '<2 FAIL'})"
    )
    lines.append(
        f"- covered_density_tiers: {len(global_summary['covered_density_tiers'])} "
        f"({'>=2 PASS' if len(global_summary['covered_density_tiers']) >= 2 else '<2 FAIL'})"
    )
    lines.append(
        f"- dispersion_ok: {global_summary['dispersion_ok']} "
        f"({'PASS' if global_summary['dispersion_ok'] else 'FAIL'})"
    )
    lines.append("")
    lines.append(f"- **promotion_ready: {promotion_ready}**")
    lines.append("")
    lines.append("No chunk_max_tokens promotion is performed by this aggregation. "
                 "No pipeline_config.json mutation. No runtime default change.")
    lines.append("")
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    print(f"Wrote {OUT_JSON}")
    print(f"Wrote {OUT_MD}")
    print(json.dumps(payload["global"], ensure_ascii=False, indent=2))
    print(json.dumps(payload["promotion_readiness"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
