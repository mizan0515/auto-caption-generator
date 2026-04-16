---
doc_type: dad-session-summary
session_id: 2026-04-16-a4-acquisition-followup
session_status: converged
turns: 2
---

# 2026-04-16 — A4 Acquisition Follow-up (Session Summary)

Session id: 2026-04-16-a4-acquisition-followup
Status: active (claude-code Turn 1; awaiting Codex peer-verify)
Turns: 1

## Scope

Closes the three open measurement issues Codex flagged on seal of
2026-04-16-a4-genre-acquisition-execute:

- Labeling schema for genre axis.
- W5 (11688000) chat acquisition feasibility.
- W4 offset (12702452 @1800s) chat feasibility + re-measure.

New artifacts only. 2026-04-15 A4 tracked raw+md remain byte-identical
to HEAD. The prior 2026-04-16 genre-acquisition raw+md remain
sister-only untracked carry-forward artifacts, so HEAD byte-identity
does not apply to them.

## What happened

- Labeling schema fixed at two fields: platform_category
  (authoritative, from Chzzk videoCategoryValue) and
  content_judgement (optional annotation). Every row and cell in the
  new raw JSON carries both fields; global block carries
  labeling_schema.promotion_axis_uses=platform_category.
- W5 chat pulled via pipeline.chat_collector.fetch_all_chats
  (cookieless public API). 1544 messages, 1799.5s coverage, density
  51.48 msgs/min (medium tier). Sister work/11688000/11688000_chat.log.
- W4 offset chat pulled by paginating from t=0 to 3600s and
  filtering the [1800, 3600) window, because an arbitrary
  playerMessageTime=1800000 request does not directly yield the
  desired relative offset slice. 2444 messages, 1798.9s
  coverage, density 81.52 msgs/min (high tier). Sister
  work/12702452/12702452_chat_offset1800s.log with rebased
  [00:00, 30:00) timestamps.
- Re-measurement via experiments/a4_measure_followup.py produced
  experiments/results/2026-04-16_phase-a4-acquisition-followup_raw.json
  + companion .md. Both cells insufficient_data=false. W4f 3/4
  valid (chunk 1 retry-collapse reproduced). W5f 3/3 valid. Global
  decision per_cell_multiplicative, covered_cell_count=2 within
  session. Cross-session {W1, W2, W3, W4f, W5f} = 5 valid cells if
  aggregated, but that aggregation is deferred.

## Key findings

- Chzzk chat API is cookieless. Step 0 cookie probe from the
  previous session is a prerequisite for VOD media download, not
  for chat acquisition.
- VOD 11688000 is not no-chat. It has 1544 messages in the first
  30 minutes. The previous session's no-chat framing for W5 was a
  data-absence artifact of not having attempted the pull.
- VOD 12702452 chat extends well past the 1800s cut-off on the
  existing live log. The log was truncated at collection time
  because max_duration_sec=1800 was applied.
- Within-chunk retry protocol in experiments/a4_measure.py still
  has the cache-TTL gap: initial warm populates the cache before
  the 5-second retry sleep expires, so retry_cold receives
  cache_creation_input_tokens=0. W4f chunk 1 reproduced this. The
  cell is still insufficient_data=false because the other three
  chunks passed on first pair, but the protocol is still brittle
  for any future no-chat cell.
- median_additive_overhead in chat-fed follow-up cells is
  8242-8286, versus 7912-7913 in the 2026-04-16 no-chat cells and
  7604-7900 in the 2026-04-15 A4 chat-fed cells. Scales weakly
  with chat size, consistent with A2's template-bound overhead
  claim.

## Safety invariants held

- No pipeline code edit.
- No pipeline_config.json mutation.
- No runtime chunk_max_tokens default change.
- No overwrite of 2026-04-15 A4 raw/md.
- No overwrite of 2026-04-16 genre-acquisition raw/md.
- No live work/ mutation.
- No git ref mutation live or sister.
- No remote push.
- No Chzzk cookie value in any log; chat API is cookieless.
- No full-pipeline end-to-end smoke executed.

## Deferred

- Cross-session aggregation across {W1, W2, W3, W4f, W5f} via a
  single evaluate_global call.
- Within-chunk retry protocol fix in experiments/a4_measure.py.
- End-to-end smoke session 2026-04-16-a4-end-to-end-smoke.

## Handoff

## Turn 2 peer verification

Codex independently reproduced the baselines, both chat probes, the
new raw JSON arithmetic, and the sister validators.

Verified facts:

- W5 chat probe reproduces COUNT=1544, COVERAGE=1799.549, DENSITY=51.4796.
- W4 offset probe reproduces WINDOW_COUNT=2444, COVERAGE=1798.9,
  DENSITY=81.5169.
- W4f chunk 1 retry.user_attributable is literally 2 in the raw JSON.
- The 2026-04-15 A4 raw/md files are byte-identical to HEAD.
- No cookie substring leak appears in the packet, state, summaries,
  helper scripts, or new artifacts.
- Sister validators both PASS.

## Turn 2 corrections

Two wording-level claims from Turn 1 were corrected.

1. W4 direct-seek wording:
   an arbitrary playerMessageTime=1800000 request does not directly
   yield the desired relative offset slice. The successful method is
   paginate-from-t=0 plus post-filtering. The earlier "returned
   NO_CHAT" wording was too strong.

2. HEAD byte-identity scope:
   the 2026-04-15 A4 files are tracked and HEAD-identical. The prior
   2026-04-16 genre-acquisition files are sister-only untracked
   carry-forward artifacts, so HEAD byte-identity does not apply to
   them.

## Updated handoff

No further acquisition session is required. Open
2026-04-16-a4-end-to-end-smoke next, but attach cross-session
aggregation across {W1, W2, W3, W4f, W5f} as Step 0 in that smoke
contract before the actual end-to-end run starts.
