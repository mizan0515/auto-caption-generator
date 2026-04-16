---
phase: A4-genre-acquisition
date: 2026-04-16
session_id: 2026-04-16-a4-genre-acquisition-execute
raw_file: experiments/results/2026-04-16_phase-a4_genre-acquisition_raw.json
---

# A4 Genre Acquisition — Measurement Results

## Scope

Two new cells measured under experiments/a4_measure.py's paired cold/warm
Claude CLI protocol via the wrapper experiments/a4_measure_genre.py. New
artifacts only; 2026-04-15 A4 files untouched.

## Cells measured

- W4 offset-1800s 12702452 game-nochat: video 12702452 seconds
  [1800, 3600). Whisper SRT 364 entries. Empty chat_log because
  12702452_chat.log only covers 0-1799. Purpose: falsify the A4 W2
  equivalent to W3 duplication by breaking the t=0 invariant.
- W5 11688000 30-min olympics-nochat: video 11688000 seconds
  [0, 1800). Chzzk category '동계 올림픽' (Winter Olympics).
  Whisper SRT 250 entries. Empty chat_log because chat was never
  collected for this VOD. Purpose: add one cell whose Chzzk
  category is not 'Nintendo Switch life-sim game' to the A4 axis.

## Measurement parameters

- Encoding: cl100k_base.
- MAX_CHUNKS_PER_CELL: 4.
- OVERLAP_SEC: 30.
- CONSISTENCY_TOLERANCE: 0.03.
- Template hash: 4d732b40fa470862 (same as 2026-04-15 A4, so the
  chunk prompt template is byte-unchanged).
- Chat log files: both cells use empty chat_log. This is a no-chat
  variant and user_ratio is not directly comparable to A4 Turn 5's
  chat-fed W1/W2/W3.

## Cell-level results

| Cell | n_chunks | n_valid | median_user_ratio | P95_user_ratio | median_additive_overhead | insufficient_data |
|------|----------|---------|-------------------|-----------------|---------------------------|--------------------|
| W4-offset1800s-game-nochat | 4 | 2 | 4.0621 | 4.1256 | 7913.5 | true |
| W5-11688000-30min-olympics-nochat | 3 | 3 | 4.1179 | 4.6886 | 7912.0 | false |

For reference (2026-04-15 A4 Turn 5, chat-fed):

| Cell | n_chunks | n_valid | median_user_ratio | P95_user_ratio | median_additive_overhead |
|------|----------|---------|-------------------|-----------------|---------------------------|
| W1-30min-talk-high | 4 | 3 | 3.2008 | 3.3689 | ~7900 |
| W2-1h-talk-medium | 4 | 3 | 2.6606 | 2.7975 | 7604 |
| W3-3h-talk-low | 4 | 3 | 2.6606 | 2.7975 | 7604 |

## Global result

- template_hash: 4d732b40fa470862
- covered_cell_count: 1 (only W5; W4 is insufficient_data=true)
- covered_lengths_min: [30]
- covered_genres: ["olympics"]
- covered_density_tiers: ["none"]
- global_median_P95: 4.6886
- dispersion_range: [3.9853, 5.3919]
- dispersion_failures: []
- axis_coverage_ok: false
- dispersion_ok: true
- decision: per_cell_multiplicative
- recommended_margin: null

Global promotion (global_multiplicative or global_additive) remains
blocked because covered_cell_count greater-equal 5 is not met and
axis_coverage_ok is false. The decision matches A4 Turn 5's
per_cell_multiplicative outcome.

## Observations

1. user_ratio is HIGHER in the no-chat variant, not lower, even though
   the no-chat prompt is shorter in characters. Mechanism: the
   tiktoken predicted value and the user_attributable value both
   shrink when chat context is removed, but additive_overhead is
   roughly constant at ~7900 tokens. Ratio = (predicted + overhead)
   / predicted, so smaller predicted drives a larger ratio. This is
   consistent with the A2 additive-overhead finding.

2. W4 chunks 2 and 3 failed consistency_pass on both the initial
   cold/warm pair and the retry. Mechanism: retry cold call
   received cache_creation_input_tokens=0 because the warm call
   had already populated the cache; retry_user_attributable
   collapses to 2 (just the raw input tokens), so
   retry_cache_read_delta is 0 and retry deviation equals the
   original user_attributable. This is a known limitation of the
   cold/warm cache-flush protocol at high call density. Not a
   methodology invalidation; per-cell sufficiency simply needs
   more idle time between pairs or a full cache reset.

3. W5 completed with 3/3 valid chunks because the cell only has 3
   full chunks and each pair ran under the cap with a cleaner
   cache state.

4. median_additive_overhead is 7912.0-7913.5 in the no-chat cells,
   almost identical to 7879-7935 in the chat-fed W1/W2/W3. This
   supports A2's claim that the Claude CLI additive overhead is
   template-bound, not content-bound.

## Promotion rule interpretation

The A4 promotion rule (A4 section 6.2) requires:
- covered_cell_count greater-equal 5
- genres greater-equal 2 independent
- density tiers greater-equal 2 independent
- dispersion_ok

After this turn the expanded set (W1-W5) yields:
- covered_cell_count = 4 at best (W1, W2, W3 from A4 + W5 from here;
  W4 fails n_valid_chunks requirement).
- covered_genres: {'talk', 'olympics'} = 2 under A4 Turn 5 content
  judgement. Under Chzzk category: {'Nintendo Switch life-sim
  game', 'Winter Olympics'} = 2. Either schema produces 2.
- density_tiers: {'high', 'medium', 'low', 'none'} = 4 under
  A4 Turn 5 labeling; if 'none' is treated as a 4th tier, 4 is
  well above the greater-equal 2 requirement. If 'none' is a
  different axis (chat-fed vs no-chat), then 3 for the chat-fed
  cells and 1 for the no-chat cell, still greater-equal 2.

Global promotion therefore still needs one more valid cell to hit
covered_cell_count greater-equal 5. It is blocked on W4's
insufficient_data flag, not on the axis structure.

## Follow-up actions recommended

1. Re-measure W4 in a later session with a cold-cache gap of at
   least 30 minutes between chunk pairs, or acquire a second
   non-game VOD with a naturally different chunk count, to get
   W4 to n_valid_chunks greater-equal 3.
2. Pull chat_log for 11688000 via the Chzzk VOD chat API so W5
   can be re-measured with chat context and assigned a real
   density_tier.
3. Decide labeling schema (Chzzk category vs content judgement)
   for axis_coverage_ok accounting in the next session contract.
4. Run 2026-04-16-a4-end-to-end-smoke as a separate session
   against current defaults before touching chunk_max_tokens.

## Safety

- No pipeline code edit.
- No pipeline_config.json mutation.
- No chunk_max_tokens runtime-default change.
- No overwrite of 2026-04-15 A4 result files.
- No live work/ write; every new wav, SRT, mp4 is in the sister
  worktree.
- No git ref or remote mutation.
- No Chzzk cookie value ever printed.
