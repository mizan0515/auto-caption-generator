# Session Summary — 2026-04-16-a4-expansion-preflight

## Scope

Plan-only preflight for the A4 follow-up. No pipeline code, no
config value, no live or sister git ref, no remote, no
experiments/results rewrite, no sealed-session artifact edit.
Only this session's four DAD files plus the sister root state
mirror were written, and only on the sister worktree. Live is
read-only for baseline + asset-existence confirmation.

## Why preflight-only is correct now

A3 Turn 5 locked 3.35x as scoped PASS but forbade config
promotion (A3 §6.5). A4 Turn 5 measured three cells and landed
on per_cell_multiplicative because (a) axis_coverage_ok=false
(only 1 genre, nominal 3 density tiers but W2 and W3 are not
independent cells), (b) dispersion_ok=false (W1 P95 3.2008
exceeds the +/-15% global-median band [2.2615, 3.0597]). A4
§6.4 records runtime cfg decision: chunk_max_tokens stays None.
progress_report §0 reinforces: config change blocked until
A3b/A4 scope is confirmed. progress_report §2.8 records: no
full-pipeline end-to-end smoke has ever been run on the current
defaults.

Before opening an execute session, three blockers must be named
and their resolution paths chosen:

1. Cookie readiness uncertainty. pipeline_config.json has
   NID_AUT and NID_SES non-empty, but Chzzk API validity is
   untested.
2. W2 and W3 numerical identity. A4 §6.2 roots this in same
   VOD + t=0 start + chat_log coverage only 0-1799s.
3. Genre axis single coverage. A4 covers only (talk, *); no
   non-talk raw asset exists under work/.

A preflight session resolves the three on paper and hands the
next execute session a concrete Step 0 / Step 1 / Step 2
ladder.

## Readiness (all PASS)

| Check | Expected | Actual |
|-------|----------|--------|
| claude ping auth probe | result success | pong in 2.8s |
| sister worktree branch + HEAD | main @ d97514e | main @ d97514e |
| sister status | 5 experiments scratch files | same 5 files |
| live HEAD | detached d97514e | detached d97514e |
| live status line count | 13 (12 residue + 1 new session dir expected) | 13 |
| remote | only refs/heads/main @ d97514e49... | confirmed |
| PR 7 state | MERGED into main at mergeCommit d97514e49... | confirmed |
| d97514e ancestor of origin/main | exit 0 | exit 0 |

## A3 / A4 / progress_report — current ruling

- A3 (`experiments/results/2026-04-15_phase-a3_token-margin-sampling.md`)
  confirms scoped PASS at 3.35x for 30min + talk + high-density
  (A3 §5 aggregates, A3 §6.1 recommendation). A3 §6.5 explicitly
  defers config change to A3b/A4.
- A4 (`experiments/results/2026-04-15_phase-a4_generalization.md`)
  confirms per_cell_multiplicative only. W1 3.37x, W2 2.80x,
  W3 2.80x. A4 §6.2 documents W2=W3 numerical identity. A4 §6.4
  retains `chunk_max_tokens=None` at runtime. A4 §8 records
  genre single-coverage + cookie validity unverified as open
  risks.
- progress_report §2.8 confirms the full-pipeline end-to-end
  smoke has never been run with the new chunk_max_chars=8000
  and chunk_overlap_sec=30 defaults.

## Preflight inventory

### Raw assets under work/12702452 (live only)

- `12702452_..._144p.mp4` — full-VOD source for ffmpeg cuts.
- `..._144p_clip1800s.srt` — A3/A4 W1.
- `..._144p_clip3600s.{mp4,srt}` + `..._144p_clip3600s_part001.wav`
  — A4 W2 asset set.
- `..._144p_clip10800s.{mp4,srt,wav}` — A4 W3 triple.
- `12702452_chat.log` — coverage 0 to 1799s only.
- Sister has no `work/` dir (gitignored).

### A3/A4 experiment scripts (sister)

- `experiments/a4_measure.py` (16,158 bytes)
- `experiments/_a4_transcribe_wav.py` (2,389 bytes)
- `experiments/_a4_cells.json` (2,033 bytes)
- `experiments/_a4_paths.json` (1,763 bytes)
- `experiments/a3_measure.py` (9,789 bytes)

### Pipeline code entry points (sister, alive)

- `pipeline/downloader.py` (249 lines, `download_vod_144p`
  at line 180).
- `content/network.py` (208 lines, NetworkManager with
  extract_content_no, get_video_info, get_video_dash_manifest,
  get_video_m3u8_manifest, get_video_m3u8_base_url,
  get_clip_info, get_clip_manifest).
- `pipeline/monitor.py` (194 lines, check_new_vods at line 100,
  fetch_vod_list at line 25, extract_channel_id at line 19,
  parse_vod_info at line 40).
- `pipeline/config.py` (110 lines; DEFAULT_CONFIG has
  chunk_max_chars=8000, chunk_max_tokens=None,
  chunk_tokenizer_encoding=cl100k_base, chunk_overlap_sec=30).

### pipeline_config.json state

- File exists.
- Saved keys (sorted): auto_cleanup, bootstrap_latest_n,
  bootstrap_mode, chunk_max_chars, chunk_overlap_sec,
  claude_timeout_sec, cookies, download_resolution,
  fmkorea_enabled, fmkorea_max_pages, fmkorea_max_posts,
  fmkorea_search_keywords, output_dir, poll_interval_sec,
  streamer_name, target_channel_id, work_dir.
- cookies subkeys: NID_AUT, NID_SES (both non-empty).
- Chzzk API validity of those cookies: untested this turn.
- chunk_max_tokens key: absent from the saved config, so the
  runtime effective value inherits DEFAULT_CONFIG None.

### What is missing for next execute

| Row | State | Acquisition path |
|-----|-------|------------------|
| Non-talk raw asset | missing | Chzzk VOD via pipeline.downloader after cookie probe |
| Independent density-tier sample | missing | different VOD OR ffmpeg -ss on 12702452 at >= 1800s offset |
| Cookie Chzzk API validity | unknown | NetworkManager.get_video_info on a known VOD id |
| Full-pipeline end-to-end smoke on current defaults | never run | pipeline/main.py oneshot after Step 0 passes |
| chunk_max_tokens runtime default recalculation | deferred | do nothing this chain; a later session |

## Three judgment questions

### Q1 — Minimum new cells for global promotion

Answer: at least 3 new independent cells, with at least one
non-talk genre and at least one medium-density cell that is
not t=0 of an existing VOD.

Evidence: A4 §5.3 covered_cell_count=3 with axis_coverage_ok
=false. Promotion rule (A4 C2) requires covered >= 5, genres
>= 2, density tiers >= 2 independent, dispersion_ok. W2 and
W3 reduce to one independent cell under A4 §6.2, so effective
count today is 2. Reaching 5 requires 3 more, of which 1 must
be non-talk and 1 must be medium-density from a different VOD
or offset. W1 P95 3.2008 also overshoots the +/-15% band
[2.2615, 3.0597], so new samples must either pull the median
up or confirm W1 is an outlier to unlock dispersion_ok.

### Q2 — Bundle genre acquisition and smoke or split

Answer: split into two sequential sessions. Genre acquisition
first; end-to-end smoke only after acquisition converges.

Evidence: acquisition depends on cookie validity (unverified)
and Chzzk VOD availability; likely failure modes include 401
on `get_video_info`, no non-talk VOD on the configured
`target_channel_id`, and manifest URL expiry. A bundled smoke
session has no target if acquisition fails. progress_report
§2.8 treats smoke as a distinct verification surface
(output/*.md, *.html, *.json) orthogonal to A4 cell
measurement; separate checkpoint sets are cleaner.

### Q3 — First action priority

Answer: cookie readiness probe FIRST, then new-VOD acquisition,
with resampling at non-zero offset as fallback if cookies are
dead.

Evidence: pipeline_config.json has NID_AUT and NID_SES non-
empty but nothing proves they work against Chzzk. A4 §8 open
risk 1 explicitly records 'cookie boolean=True만 확인,
유효성은 미검증'. content/network.py NetworkManager
.get_video_info is the cheapest probe (single GET, no
download). On PASS proceed to acquisition; on 401/403 refresh
cookies out-of-band before acquisition; as a last resort,
resample 12702452 at a non-zero offset to break W2=W3
duplication on the talk axis.

## Recommended next-session ladder

1. `2026-04-16-a4-genre-acquisition-execute` (Step 0 cookie
   probe -> Step 1 non-talk acquisition + new cell -> Step 2
   W2/W3 de-duplication by offset or VOD change).
2. `2026-04-16-a4-end-to-end-smoke` (separate session, runs
   after acquisition converges; new VOD through full pipeline;
   verifies output/*.md + *.html + *.json creation on current
   defaults).

Do not bundle. Do not promote `chunk_max_tokens` in either
session.

## Safety audit

- No `pipeline/*` edit, no `pipeline_config.json` edit.
- No `experiments/results/*` edit.
- No live or sister `git` ref mutation, no remote mutation.
- No sealed A4 or G-UNRELATED-DIRTY session artifact edit.
- No Chzzk cookie value inspection or logging; only presence +
  non-emptiness of NID_AUT and NID_SES was probed.

## Open risks (for posterity)

1. Cookie Chzzk API validity untested. Execute session must
   start with probe.
2. Configured target_channel_id may not have non-talk VODs;
   execute session must confirm availability or pick an
   alternate channel.
3. W2 = W3 numerical identity is a structural bug; new
   acquisition must break same-VOD + t=0 + chat_log window or
   the new cell collapses.
4. Full-pipeline end-to-end smoke never run on new defaults;
   smoke session must verify output artifact triple.
5. 8 pre-existing Validate-Documents + 4 Validate-DadPacket
   failures remain accepted-residue for a separate cleanup
   session.
6. Phase label drift between progress_report.md and A3/A4
   scope definitions persists (A4 §1, §8.4). Resolve in a
   doc-sync turn before promotion.

## Handoff

Codex Turn 2 on THIS session peer-verifies:

1. three blockers (cookie unknown, W2=W3, genre single-
   coverage) are real from live docs and code;
2. asset inventory table is reproducible on sister and
   where live-only, verifiable by read on live;
3. recommended next-session shape (cookie probe FIRST,
   acquisition split from smoke) is the minimum sufficient
   decomposition;
4. no pipeline/config/result file was mutated by this
   preflight, and no git ref or remote mutated.

If Codex agrees, this session seals converged and the next
execute session opens as `2026-04-16-a4-genre-acquisition-execute`.

## Turn 2 peer verification

Codex re-ran the requested peer checks and confirmed the three
core blockers are real:

1. cookie validity is still unknown because this preflight only
   proved `pipeline_config.json` cookie-field presence and did not
   call `content/network.py` `NetworkManager.get_video_info`
2. W2 and W3 are numerically identical in A4 §5.1 and the same-VOD
   + t=0 + chat_log 0-1799s explanation in A4 §6.2 still holds
3. genre coverage is still single-axis with `covered_genres =
   ["talk"]` and `axis_coverage_ok = false`

One documentary drift was found and fixed in place: the live
inventory does not contain `..._clip3600s.wav`; the actual W2 wav
asset is `..._clip3600s_part001.wav`. Turn 1 packet and this summary
now reflect the exact on-disk names.

The recommended ladder remains minimum-sufficient:

1. `2026-04-16-a4-genre-acquisition-execute`
   with mandatory Step 0 cookie probe, then non-talk acquisition,
   then W2/W3 de-duplication by offset or VOD change
2. `2026-04-16-a4-end-to-end-smoke`
   only after acquisition converges

No pipeline/config/result/git-ref/remote mutation slipped in. This
session stays converged and authorizes opening the genre-acquisition
execute session next.
