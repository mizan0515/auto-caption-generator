---
doc_type: dad-session-summary
session_id: 2026-04-16-a4-end-to-end-smoke
session_status: converged
turns: 2
---

# 2026-04-16 — A4 End-to-End Smoke (Session Summary)

Session id: 2026-04-16-a4-end-to-end-smoke
Status: converged (Codex Turn 2 peer-verified)
Turns: 2

## Scope

Executes the A4 end-to-end smoke explicitly recommended by Codex at
seal of 2026-04-16-a4-acquisition-followup. The contract attaches
cross-session aggregation as Step 0 ahead of the smoke body.

## What happened

- Step 0 cross-session aggregation ran deterministically over three
  existing raw JSONs (2026-04-15 A4, 2026-04-16 genre-acquisition,
  2026-04-16 acquisition-followup) via a single evaluate_global pass
  using experiments/a4_aggregate_cross_session.py. Non-overwriting
  output at experiments/results/2026-04-16_phase-a4_cross-session-aggregation_raw.json
  and .md. platform_category is named authoritative axis label per
  the acquisition-followup schema fix.
- Aggregated global: covered_cell_count=3 (W4f, W5f,
  W5-olympics-nochat), covered_platform_category_count=2,
  covered_density_tiers=3 (high, medium, none),
  global_median_P95=3.2994, dispersion_range=[2.8045, 3.7943],
  dispersion_failures=['W5-11688000-30min-olympics-nochat']
  (P95=4.6886 is an outlier against the chat-fed P95≈3.0),
  axis_coverage_ok=false, dispersion_ok=false,
  decision=per_cell_multiplicative. Promotion gate FAIL.
- Full-pipeline smoke via python -m pipeline.main --process 11688000
  --limit-duration 1800 ran in the sister worktree with pipeline_config.json
  copied from live (gitignored in both). Every stage PASS: VOD info
  lookup, existing-file download short-circuit, clip to 1800s, chat
  collection 1600→1544, fmkorea scrape 20 posts, highlight analysis
  6 peaks, Whisper large-v3-turbo transcription, char-based chunking
  at 150000/45s, Claude summarization within 300s timeout, md+html+
  metadata generation. output/pipeline_state.json records
  processed_vods[11688000].status=completed at 05:23:58.
- Smoke output regression via inline runner (existing
  experiments/test_parser.py and test_html_render.py hardcode VOD
  12702452 which does not exist in sister):
  _parse_summary_sections extracts 13 timeline entries, 5
  highlights, 2 editor-notes items. _generate_html renders
  20676 chars with valid DOCTYPE when called with the smoke chats
  and metadata-backed highlights. 4-file summarizer unit is green.

## Key findings

- Step 0 corrected a documentary overclaim from the prior seal:
  "{W1, W2, W3, W4f, W5f} = 5 valid cells if aggregated" is not
  true. Honest evaluate_global says covered_cell_count=3. W1/W2/W3
  are all insufficient_data=true in the committed 2026-04-15 A4 raw
  JSON because the initial pair was also cache-hot, collapsing
  user_attributable to 2 on every chunk. W4-offset1800s-game-nochat
  from the genre-acquisition raw is also insufficient (2/4 valid).
- Pooled dispersion now fails because the no-chat W5 cell
  (P95=4.6886) is an outlier against chat-fed W4f/W5f (P95≈3.0).
- Full pipeline runs green on current defaults (chunk_max_chars=150000,
  chunk_overlap_sec=45, chunk_max_tokens unset, claude_timeout_sec=300).
  No runtime-default change is required for wiring correctness.
- Whisper/Silero tqdm progress bars currently go to the pipeline
  log as a single 158-KB line via carriage-return overwriting. Not
  a pipeline defect, but an experiments-hygiene gap.

## Safety invariants held

- No pipeline_config.json mutation on either worktree.
- No pipeline code edit.
- No runtime chunk_max_tokens default change.
- No overwrite of 2026-04-15 A4 tracked raw/md.
- No overwrite of 2026-04-16 genre-acquisition untracked raw/md.
- No overwrite of 2026-04-16 acquisition-followup untracked raw/md.
- No live worktree write (smoke ran from sister cwd).
- No git ref mutation on either worktree.
- No remote push.
- No Chzzk cookie value printed to log, packet, state, summaries,
  or new artifacts.
- No full-pipeline run on live worktree.

## Deferred

- Re-measurement of W1/W2/W3 under a cache-TTL-aware retry protocol
  (MIN_RETRY_IDLE_SEC ≈ 330–360s or prefix-perturbation trick).
- Dispersion policy when pooling no-chat and chat-fed cells (drop
  nochat or document a two-tier band).
- chunk_max_tokens runtime-default promotion.
- Making experiments/test_parser.py and test_html_render.py
  argv-parameterized so they run against any smoke output.

## Handoff

Codex Turn 2 should peer-verify this session. Specifically: baseline
+ remote + ancestor, aggregation arithmetic,
pipeline_state.json+output-file existence, inline summarizer-unit
regression, no chunk_max_tokens promotion, no pipeline_config.json
mutation, no live worktree write, no Chzzk cookie leak, sister
validators PASS. Correct any wording overclaim in-place and seal.
No further DAD session should be opened in Turn 2.

## Turn 2 Peer Verify

- Codex independently reproduced sister `main@d97514e`, live detached
  `d97514e`, remote refs/heads/main only, and
  the merge-base ancestor check for `d97514e -> origin/main` exit 0.
- Step 0 aggregation reran deterministically. The authoritative schema
  is present at the top-level `labeling_schema` block, while
  `covered_platform_category_count=2` lives under
  `promotion_readiness`. The promoted decision remains
  `per_cell_multiplicative` with `promotion_ready=false`.
- Two wording-level overclaims were corrected in-place:
  `output/pipeline_state.json` stores `processed_vods[11688000].status`, not a
  top-level `status`; and the inline `_generate_html(...)` regression
  renders 20676 chars, not 18072, when called with the actual smoke
  chats and metadata-backed highlights.
- pipeline_config hashes match live, no cookie substring appears in the
  session surface or new artifacts, and sister validators PASS.
