# 2026-04-16 — A4 Expansion Preflight (Session Summary)

Session id: 2026-04-16-a4-expansion-preflight
Status: converged (preflight-only, plan packet)
Turns: 1

## What happened

Plan-only preflight for the A4 follow-up. Re-confirmed from
live files that A3 (3.35x scoped) and A4 (per_cell_multiplicative
scoped) cannot be promoted to runtime default because genre
axis is single (talk only), W2 and W3 are not independent cells
(same VOD + t=0 start + chat_log coverage only 0-1799s), and
the full-pipeline end-to-end smoke has never been run on the
current defaults.

Inventoried raw assets under `work/12702452`, all four A4
experiment scripts and `a3_measure.py` in the sister worktree,
and the pipeline code paths (`pipeline/downloader.py`,
`content/network.py`, `pipeline/monitor.py`,
`pipeline/config.py`) that the next execute session will need.
Confirmed `pipeline_config.json` holds non-empty NID_AUT and
NID_SES but did not verify Chzzk API validity.

Authored a concrete ladder for the next execute session
(cookie probe -> non-talk acquisition -> W2/W3 de-duplication)
with a separate end-to-end smoke session afterward.

## Key findings

- Promotion rule (A4 C2) remains FAIL. Current covered_cell_count
  is nominally 3 but effectively 2 independent cells (W1 plus
  W2 equivalent to W3).
- chunk_max_tokens runtime default stays None (A4 §6.4). The
  saved pipeline_config.json does not override it.
- Cookies are structurally present but API-valid status is
  unknown. The next execute session MUST start with a cookie
  probe.
- Full-pipeline end-to-end smoke (progress_report §2.8) is
  still a zero-run gap and is a separate session in the
  proposed ladder.

## Recommended next-session ladder

1. `2026-04-16-a4-genre-acquisition-execute`
   Step 0: cookie probe via content/network.py NetworkManager
   get_video_info on a known VOD id.
   Step 1: on PASS, new non-talk Chzzk VOD acquisition via
   pipeline.downloader.download_vod_144p, wav extract,
   `experiments/_a4_transcribe_wav.py`, and feed the new cell
   into `experiments/a4_measure.py` with MAX_CHUNKS_PER_CELL=4.
   Step 2: resample existing 12702452 VOD at a non-zero start
   offset (>= 1800s) to break W2 equivalent to W3 duplication
   on the talk axis.

2. `2026-04-16-a4-end-to-end-smoke`
   Separate session after acquisition converges. Run
   `pipeline/main.py` oneshot on the new VOD through
   monitoring -> download -> chat -> transcribe -> summarize
   -> html. Verify `output/*.md`, `output/*.html`, and
   `output/*.json` are created on current defaults
   (chunk_max_chars=8000, chunk_overlap_sec=30).

## Safety

- No pipeline code edit.
- No pipeline_config.json value change.
- No live or sister git ref mutation.
- No remote mutation.
- No experiments/results rewrite.
- No sealed A4 or G-UNRELATED-DIRTY artifact edit.
- No Chzzk cookie value inspection or logging.

## Handoff

Codex Turn 2 on THIS session peer-verifies:
(a) the three promotion blockers (cookie validity unknown,
W2 and W3 duplication, genre single-coverage) are real from
live files and code; (b) the asset and script inventory is
reproducible; (c) the split ladder (acquisition first, smoke
after) is the minimum sufficient decomposition; (d) no
pipeline, config, or result file was mutated by this
preflight.

If Codex agrees, this session seals converged and the next
execute session opens as `2026-04-16-a4-genre-acquisition-execute`.

## Turn 2 seal

Codex peer-verified Turn 1 and confirmed:

- the three promotion blockers are real
- the asset and script inventory is reproducible
- the split ladder is the minimum sufficient decomposition
- no pipeline/config/result mutation occurred

One packet-level drift was corrected: the W2 wav asset is
`..._clip3600s_part001.wav`, not `..._clip3600s.wav`.

The session remains converged and the next authorized session is
`2026-04-16-a4-genre-acquisition-execute` with Step 0 cookie probe
mandatory.
