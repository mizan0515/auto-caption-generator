---
doc_type: dad-session-summary-named
session_id: 2026-04-16-a4-end-to-end-smoke
session_status: converged
turns: 2
---

# 2026-04-16 — A4 End-to-End Smoke (Session Summary)

Session id: 2026-04-16-a4-end-to-end-smoke
Status: active (claude-code Turn 1; awaiting Codex peer-verify)
Turns: 1

## Outcome

- Step 0 cross-session aggregation completed via
  experiments/a4_aggregate_cross_session.py. Non-overwriting output
  at experiments/results/2026-04-16_phase-a4_cross-session-aggregation_raw.json
  and .md. platform_category is the authoritative axis label.
  covered_cell_count=3 (W4f, W5f, W5-olympics-nochat),
  covered_platform_category_count=2, covered_density_tiers=3
  (high, medium, none), global_median_P95=3.2994,
  dispersion_failures=['W5-11688000-30min-olympics-nochat']
  (P95=4.6886 is an outlier against chat-fed P95≈3.0),
  axis_coverage_ok=false, dispersion_ok=false,
  decision=per_cell_multiplicative. Promotion gate FAIL.
- Full-pipeline smoke via python -m pipeline.main --process 11688000
  --limit-duration 1800 ran in the sister worktree with
  pipeline_config.json copied from live (gitignored in both; sister
  copy byte-identical to live). Every stage PASS.
  output/pipeline_state.json records
  processed_vods[11688000].status=completed at 05:23:58.
- Smoke output regression via inline summarizer-unit runner:
  _parse_summary_sections extracts title, 5 hashtags, 13 timeline
  entries, 5 highlights, 2 editor-notes items. _generate_html
  renders 20676 chars with valid DOCTYPE when called with the smoke
  chats and metadata-backed highlights.

## Data-integrity note

Step 0 surfaced that the prior seal's 5-cell-if-aggregated framing
was an overclaim. Honest evaluate_global output is 3 valid cells.
W1/W2/W3 are all insufficient_data=true in the committed 2026-04-15
A4 raw JSON because the initial pair was also cache-hot, collapsing
user_attributable to 2 on every chunk.

## Safety invariants held

- No pipeline_config.json mutation on either worktree.
- No pipeline code edit.
- No runtime chunk_max_tokens default change.
- No overwrite of 2026-04-15 A4 tracked raw/md.
- No overwrite of 2026-04-16 genre-acquisition untracked raw/md.
- No overwrite of 2026-04-16 acquisition-followup untracked raw/md.
- No live worktree write; smoke ran from sister cwd.
- No git ref mutation live or sister.
- No remote push.
- No Chzzk cookie value printed anywhere.

## Handoff

Codex Turn 2 should peer-verify: baseline + remote + ancestor,
Step 0 aggregation arithmetic, pipeline_state.json + output file
existence, inline summarizer-unit regression, no chunk_max_tokens
promotion, no pipeline_config.json mutation, no live worktree
write, no Chzzk cookie leak, sister validators PASS. Correct any
wording overclaim in-place and seal. Do not open a further DAD
session in Turn 2.

## Turn 2

- Codex re-ran baseline, aggregation, smoke-output verification,
  pipeline_config hash comparison, cookie leak scan, and sister
  validators.
- The execution claim stands. Only wording-level corrections were
  needed:
  `output/pipeline_state.json` stores nested
  `processed_vods[11688000].status`, and inline `_generate_html(...)`
  renders 20676 chars rather than 18072.
- Session sealed as converged. A4 promotion remains deferred; no new
  DAD session is opened from this turn.
