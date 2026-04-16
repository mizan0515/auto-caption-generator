---
doc_type: dad-session-summary-named
session_id: 2026-04-16-a4-acquisition-followup
session_status: converged
turns: 2
---

# 2026-04-16 — A4 Acquisition Follow-up (Session Summary)

Session id: 2026-04-16-a4-acquisition-followup
Status: converged (Codex Turn 2 peer-verified)
Turns: 2

## Outcome

- Labeling schema fixed: platform_category authoritative (Chzzk
  videoCategoryValue), content_judgement optional annotation.
  promotion_axis_uses=platform_category. Raw JSON every row and
  cell carries both fields.
- W5 (VOD 11688000) chat acquisition PASS. 1544 messages over
  1799.5s, density 51.48 msgs/min (medium tier). Saved to sister
  work/11688000/11688000_chat.log (82929 bytes). Chzzk chat API is
  cookieless public endpoint.
- W4 offset (VOD 12702452 @1800-3600s) chat acquisition PASS.
  An arbitrary playerMessageTime=1800000 request did not directly
  yield the desired relative offset slice; paginate-from-t=0 to
  3600s and window-filter worked: 2444 messages over
  1798.9s, density 81.52 msgs/min (high tier). Saved to sister
  work/12702452/12702452_chat_offset1800s.log (117235 bytes) with
  timestamps rebased to [00:00, 30:00).
- Re-measurement via experiments/a4_measure_followup.py wrote NEW
  raw JSON and companion .md under
  experiments/results/2026-04-16_phase-a4-acquisition-followup_*.
  W4f n_valid_chunks=3 (chunk 1 retry-collapse reproduced on first
  attempt but 3 others passed). W5f n_valid_chunks=3. Global
  decision=per_cell_multiplicative, covered_cell_count=2 within
  session. 2026-04-15 A4 tracked files are byte-identical to HEAD.
  The prior 2026-04-16 genre-acquisition files are sister-only
  untracked carry-forward artifacts, so HEAD byte-identity does not
  apply to them.

## Data-integrity note

Chzzk chat API does not directly yield the desired relative offset
slice when given an arbitrary playerMessageTime value such as
1800000. The reliable method is to follow nextPlayerMessageTime from
prior pages (that is, paginate from t=0 here) and filter the desired
window post-normalization.

## Safety invariants held

- No pipeline code edit.
- No pipeline_config.json mutation.
- No runtime chunk_max_tokens default change.
- No overwrite of 2026-04-15 A4 raw/md.
- No overwrite of 2026-04-16 genre-acquisition raw/md.
- No live work/ mutation.
- No git ref mutation live or sister.
- No remote push.
- No Chzzk cookie value printed.
- No full-pipeline end-to-end smoke executed.

## Codex Turn 2 peer verdict

- C1 PASS
- C2 PASS
- C3 PASS
- C4 FAIL-THEN-FIXED (wording corrected)
- C5 FAIL-THEN-FIXED (HEAD-identity scope corrected)

The execution thesis stands. Only documentary overclaim was fixed.

## Updated handoff

Open 2026-04-16-a4-end-to-end-smoke next, but attach cross-session
aggregation across {W1, W2, W3, W4f, W5f} as Step 0 in that smoke
contract before the end-to-end run starts.
