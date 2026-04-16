---
phase: A4-acquisition-followup
date: 2026-04-16
session_id: 2026-04-16-a4-acquisition-followup
raw_file: experiments/results/2026-04-16_phase-a4-acquisition-followup_raw.json
predecessors:
  - experiments/results/2026-04-15_phase-a4_raw.json
  - experiments/results/2026-04-15_phase-a4_generalization.md
  - experiments/results/2026-04-16_phase-a4_genre-acquisition_raw.json
  - experiments/results/2026-04-16_phase-a4_genre-acquisition.md
---

# A4 Acquisition Follow-up — Measurement Results

## Scope

Closes the three measurement issues Codex flagged on seal of
2026-04-16-a4-genre-acquisition-execute:

1. Labeling schema for genre axis.
2. W5 (VOD 11688000) chat acquisition feasibility.
3. W4 offset (VOD 12702452 at 1800-3599s) chat feasibility + re-measure.

New artifacts only. 2026-04-15 A4 raw/md remain byte-identical to HEAD.
The prior 2026-04-16 genre-acquisition raw/md are sister-only untracked
carry-forward artifacts, so HEAD byte-identity does not apply to them.

## Labeling schema decision

Every row and cell now carries two fields:

- `platform_category` — authoritative. Pulled directly from Chzzk
  `videoCategoryValue` at acquisition time. Used for
  `axis_coverage_ok` accounting and for any future A4 promotion gating.
- `content_judgement` — optional annotation. Free-text label based on
  an agent's reading of the content. Not used for promotion math.

A4 Turn 5 classified VOD 12702452 as genre 'talk' by content
judgement, but the Chzzk platform category is '더 게임 오브 라이프 포
닌텐도 스위치' (a Nintendo Switch life-simulation game). The two-field
schema preserves both readings without forcing a retcon of the older
content-judgement log.

The global block in the raw JSON records this explicitly:

```
"labeling_schema": {
  "primary": "platform_category",
  "secondary": "content_judgement",
  "promotion_axis_uses": "platform_category"
}
```

## Chat acquisition status

- **W5 (11688000)** — OK. `pipeline.chat_collector.fetch_all_chats`
  with `max_duration_sec=1800` returned 1544 messages over 1799.5s
  (density 51.48 msgs/min, "medium" tier). Saved as
  `work/11688000/11688000_chat.log` (82929 bytes). Cookieless public
  API; no auth required.
- **W4 offset (12702452, 1800-3600s)** — OK. Direct
  `playerMessageTime=1800000` request did not directly yield the
  desired relative offset slice, so the successful method was
  paginating from t=0 through 3600s and filtering the
  post-normalization [1800000, 3600000) window. That returned 2444
  messages over 1798.9s (density 81.52 msgs/min, "high" tier). Saved
  as `work/12702452/12702452_chat_offset1800s.log` (117235 bytes)
  with timestamps rebased to [00:00, 30:00) so chunker SRT-window
  math is consistent.

Both logs landed under sister `work/` only. Live `work/` is untouched.

## Measurement parameters

- Encoding: cl100k_base.
- MAX_CHUNKS_PER_CELL: 4.
- OVERLAP_SEC: 30.
- CONSISTENCY_TOLERANCE: 0.03.
- Template hash: 4d732b40fa470862 (unchanged from 2026-04-15 A4 and
  2026-04-16 genre-acquisition, so the chunk prompt template is byte-
  identical across all three generations).
- Inter-cell idle: 360s. Added between cells to let the Anthropic
  prompt cache (5-minute TTL) expire before a new cell primes a fresh
  cache. No corresponding guard was added within a cell (between the
  initial pair and the retry pair) because that would multiply chunk
  wall time by ~6x; the retry-collapse risk is documented below.

## Cell-level results

| Cell | platform_category | density | n_chunks | n_valid | median_user_ratio | P95_user_ratio | median_additive_overhead | insufficient_data |
|------|-------------------|---------|----------|---------|-------------------|-----------------|---------------------------|--------------------|
| W4f-offset1800s-12702452-chat | 더 게임 오브 라이프 포 닌텐도 스위치 | 81.52 (high) | 4 | 3 | 2.8815 | 3.2994 | 8286.0 | false |
| W5f-11688000-30min-chat | 동계 올림픽 | 51.48 (medium) | 3 | 3 | 2.6337 | 2.9456 | 8242.0 | false |

For reference the 2026-04-15 A4 Turn 5 chat-fed cells (all
platform_category '더 게임 오브 라이프 포 닌텐도 스위치'):

| Cell | density | n_valid | median_user_ratio | P95_user_ratio | median_additive_overhead |
|------|---------|---------|-------------------|-----------------|---------------------------|
| W1-30min-talk-high | ~70+ (high) | 3 | 3.2008 | 3.3689 | ~7900 |
| W2-1h-talk-medium | mid (medium) | 3 | 2.6606 | 2.7975 | 7604 |
| W3-3h-talk-low | low | 3 | 2.6606 | 2.7975 | 7604 |

## Global result (this session only)

- template_hash: 4d732b40fa470862
- covered_cell_count: 2 (W4f + W5f; this session only)
- covered_lengths_min: [30]
- covered_genres: ["game", "olympics"] — content_judgement labels
- covered_density_tiers: ["high", "medium"]
- global_median_P95: 3.1225
- dispersion_range: [2.6541, 3.5909]
- dispersion_failures: []
- axis_coverage_ok: false (covered_cell_count < 5 within this session)
- dispersion_ok: true
- decision: per_cell_multiplicative
- recommended_margin: null
- labeling_schema: platform_category primary, content_judgement
  secondary, promotion gating uses platform_category.

## Cross-session aggregation (informational)

If W1-W5 are aggregated across 2026-04-15 A4 + this follow-up:

- n_valid_cells = 5 (W1, W2, W3 from A4; W4f, W5f from here).
- platform_category axis = {'더 게임 오브 라이프 포 닌텐도 스위치',
  '동계 올림픽'} — 2 distinct values (game + olympics).
- density_tiers across the 5 cells = {high, medium, low} — 3 distinct.

A full global evaluation across 5 cells would need a single
`evaluate_global` call over merged cell summaries, which this session
does not run. That aggregation decision belongs either to the smoke
session's contract or to a dedicated aggregation session.

## Observations

1. The W4f chunk 1 retry still collapsed to
   `retry_user_attributable=2` because the initial warm call
   populated the cache before `time.sleep(5)` expired, so the retry
   cold received `cache_creation_input_tokens=0`. Chunks 2, 3, 4 of
   W4f and all three chunks of W5f passed consistency on the first
   pair without needing a retry, which is why the cells are
   `insufficient_data=false` even though the within-chunk retry
   protocol is still brittle.

2. median_additive_overhead is 8242-8286 in the chat-fed follow-up
   cells, versus 7912-7913 in the 2026-04-16 no-chat cells and
   7604-7900 in the A4 Turn 5 chat-fed cells. The ~300-400 token
   increase is consistent with the ~1000-1600 token bump in
   `cache_creation` between the no-chat (10055-10554) and chat-fed
   (11486-13600) variants; additive_overhead tracks template +
   cache overhead, which scales weakly with chat size because the
   chat region is a small fraction of the cached prefix.

3. Global `decision=per_cell_multiplicative` stays unchanged from
   both 2026-04-15 A4 Turn 5 and 2026-04-16 genre-acquisition.
   Within-session axis_coverage_ok remains false because this
   session measured only 2 cells.

## Promotion rule status

A4 §6.2 requires `covered_cell_count >= 5 AND platform_category
count >= 2 AND density_tiers >= 2 AND dispersion_ok`. After this
session the cross-session picture is:

- covered_cell_count cross-session: 5 (needs formal aggregation run)
- platform_category count: 2
- density_tiers count: 3
- dispersion_ok: true within this session; cross-session dispersion
  needs the aggregated run.

So promotion readiness is no longer blocked by a missing cell. It
is blocked by (a) not having executed a cross-session aggregation
call and (b) the end-to-end smoke still being pending.

## Follow-up actions

1. Before smoke: run a cross-session aggregation once over {W1, W2,
   W3, W4f, W5f} cell summaries using `evaluate_global` and record
   whether `axis_coverage_ok` flips true. This is a small script
   and can live in `experiments/` as a new file.
2. Smoke (`2026-04-16-a4-end-to-end-smoke`) may open. Measurement
   ambiguity is no longer the blocker.
3. Within-chunk retry protocol needs a fix before any new
   no-chat cell is measured. Recommended: insert a 330-360s idle
   between the initial pair and the retry pair so the Anthropic
   prompt cache (5-min TTL) fully evicts. Alternatively, force a
   new cache key by slightly perturbing the prompt prefix on retry.

## Safety

- No pipeline code edit.
- No `pipeline_config.json` mutation.
- No runtime `chunk_max_tokens` default change.
- No overwrite of 2026-04-15 A4 raw/md.
- No overwrite of 2026-04-16 genre-acquisition raw/md.
- No live `work/` write. Every new chat log, probe script, cells
  JSON, and measurement artifact is under sister worktree only.
- No git ref mutation, live or sister. No remote push.
- No Chzzk cookie value printed. Chat API is cookieless; cookie
  probe was not needed this session.
