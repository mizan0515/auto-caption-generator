---
doc_type: dad-session-summary
session_id: 2026-04-16-a4-genre-acquisition-execute
session_status: converged
turns: 2
---

# A4 Genre Acquisition Execute — Session Summary

## Scope

Execute the preflight-authorized A4 follow-up: Step 0 cookie probe, Step 1
non-game acquisition, Step 2 offset resample, and paired-call measurement
on the two new cells. Keep live work/ read-only. Do not promote
chunk_max_tokens. Do not overwrite 2026-04-15 A4 result files. Do not run
the full-pipeline end-to-end smoke; that stays deferred to a separate
follow-up session.

## What happened

Step 0 cookie probe against content.network.NetworkManager.get_video_info
on VOD 12702452 returned a complete video record with vodStatus ABR_HLS,
adult False, video_id present, in_key present, duration 20552s, and
Chzzk category '더 게임 오브 라이프 포 닌텐도 스위치'. That category
line surfaced the session's dominant finding: the VOD that A4 Turn 5
labeled genre 'talk' is actually Chzzk-category 'Nintendo Switch
life-simulation game'. A4's entire genre axis to date is single-category
'game' under Chzzk platform metadata.

Step 1 acquisition enumerated 60 VODs across 15 Chzzk categories on the
configured target channel. Selected VOD 11688000 (category '동계 올림픽',
duration 9463s) as the cleanest non-game axis candidate available within
the session's time budget. Downloaded via pipeline.downloader.download_vod_144p
into the sister worktree under work/11688000/, extracted the first 1800s
as a 16 kHz mono wav via ffmpeg, transcribed with Whisper large-v3-turbo
on CUDA via experiments/_a4_transcribe_wav.py. SRT has 250 entries.

Step 2 offset resample extracted seconds 1800-3599 from the existing
live 12702452 144p mp4 into the sister worktree at
work/12702452/12702452_offset1800s_clip1800s.wav, 16 kHz mono. Whisper
transcribed to SRT with 364 entries. That cell breaks the t=0
equivalence that produced W2 numerically identical to W3 in A4.

Measurement via experiments/a4_measure_genre.py ran paired cold/warm
Claude CLI calls on up to 4 chunks per new cell and wrote NEW artifacts
at experiments/results/2026-04-16_phase-a4_genre-acquisition_raw.json
and the companion .md. The 2026-04-15 A4 raw JSON and generalization .md
are byte-identical to their preflight state.

Both new cells used empty chat_log files because 11688000 has no chat
history collected yet and 12702452's chat_log only covers seconds
0-1799. The measurement is therefore a no-chat variant and is not
directly comparable in user_ratio to A4 W1/W2/W3 which used chat
context. The raw artifact labels this explicitly.

## Key findings

- Chzzk category for 12702452 is 'Nintendo Switch life-simulation game'
  (Korean label shown above), not 'talk'. A4 Turn 5's 'talk' label was
  content-judgement, not platform metadata. Axis_coverage_ok
  interpretation depends on which labeling schema governs.
- W4 (12702452 offset 1800-3599s) breaks the W2 equivalent to W3
  duplication. The duplication root cause (same VOD + t=0 + 0-1799s
  chat window) is now falsifiable by offset.
- W5 (11688000 first 1800s) is the first cell whose Chzzk category is
  not 'Nintendo Switch life-sim game'. Under Chzzk labeling the axis
  is now two-valued.
- No-chat measurement is a distinct variant. user_ratio is smaller
  without chat context because the prompt is shorter. Raw file
  records this as 'density_tier = none'.

## Cell inventory after this turn

| Cell | Source | Window | Chzzk category | A4 label | Chat |
|------|--------|--------|-----------------|----------|------|
| W1 | 12702452 | [0, 1800) | Nintendo Switch life-sim game | talk | yes |
| W2 | 12702452 | [0, 3600) | Nintendo Switch life-sim game | talk | yes, 0-1799s |
| W3 | 12702452 | [0, 10800) | Nintendo Switch life-sim game | talk | yes, 0-1799s |
| W4 | 12702452 | [1800, 3600) | Nintendo Switch life-sim game | game (offset) | none |
| W5 | 11688000 | [0, 1800) | 동계 올림픽 (Winter Olympics) | olympics | none |

## Safety

- No pipeline code edit.
- No pipeline_config.json value change.
- No runtime default chunk_max_tokens promotion.
- No overwrite of 2026-04-15 A4 result files.
- No live work/ mutation. All new wav, SRT, mp4 landed in the sister
  worktree under work/ only.
- No live or sister git ref mutation. No remote push. No branch delete.
- No Chzzk cookie value ever printed to logs or files.
- No full-pipeline end-to-end smoke executed. It stays deferred.

## Deferred work

- Full-pipeline end-to-end smoke against current defaults. Progress
  report section 2.8 still records zero runs.
- Chat download for 11688000 and for 12702452 offset 1800-3599s via
  the Chzzk VOD chat API, to re-measure W4 and W5 with chat context.
- Labeling schema decision for genre axis: Chzzk category or
  content-judgement. The next session contract must pick one before
  axis_coverage_ok can be evaluated with the expanded cell set.
- The pre-existing 8 Validate-Documents and 4 Validate-DadPacket live
  validator failures remain accepted residue and were not touched here.

## Handoff

Claude Code Turn 1 proposed the next session as
2026-04-16-a4-end-to-end-smoke. Codex Turn 2 did not accept that order.
Smoke remains separate, but it should not open yet.

## Turn 2 peer verification

Codex re-ran the sister/live/remote baselines and reproduced all five
checkpoints. The Step 0 cookie probe was independently re-run via
content.network.NetworkManager.get_video_info on 12702452 with cookies
loaded from the live runtime config but never printed. The safe-field
result matched Turn 1: video_id present, in_key present, vodStatus
ABR_HLS, adult False, duration 20552, category '더 게임 오브 라이프 포
닌텐도 스위치'.

Codex verified that the 2026-04-15 A4 raw JSON and generalization .md
are byte-identical to HEAD with git diff --exit-code plus hash-object vs
ls-tree checks. The new 2026-04-16 raw JSON arithmetic also checked out:
for every row, user_attributable equals input plus cache_creation, and
user_ratio matches user_attributable divided by predicted to the file's
four-decimal serialization precision.

Cookie leakage was explicitly checked by scanning this session packet,
its summaries, and the related A4 helper scripts/results for the exact
runtime cookie substrings. No hits were found.

## Turn 2 decisions

- Seal this execute session as converged. No checkpoint failed.
- For future axis coverage accounting, use a two-field schema:
  platform_category as the authoritative promotion label, and
  content_judgement as an optional annotation only.
- Do not open the smoke session next. W5 chat acquisition and W4
  re-measurement belong in a separate acquisition/measurement follow-up
  because they repair the measurement surface, not the end-to-end
  pipeline surface.

## Updated handoff

The next session should be a separate acquisition/measurement follow-up
that:

1. locks the labeling schema (`platform_category` primary,
   `content_judgement` secondary),
2. pulls chat for 11688000 if available,
3. re-measures W4 under a corrected protocol (and with offset-appropriate
   chat only if such chat can actually be sourced),
4. then hands off to 2026-04-16-a4-end-to-end-smoke after those
   measurement questions converge.
