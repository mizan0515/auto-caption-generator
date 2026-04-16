# 2026-04-16 — A4 End-to-End Smoke

## Session

- Session id: `2026-04-16-a4-end-to-end-smoke`
- Target VOD: `11688000` (`밀라노 올림픽 스노보드 같이 보자아 대한민국 유승은 선수 화이팅٩(●'▿'●)۶`, Chzzk category `동계 올림픽`, duration 2h37m → clipped to `--limit-duration 1800` = 30 min)
- Sister HEAD: `d97514e` (tracked pipeline bytes identical to committed state)
- Template hash: `4d732b40fa470862`

## Step 0 — cross-session aggregation

Source raw JSONs (3):

- `experiments/results/2026-04-15_phase-a4_raw.json` — W1/W2/W3 (all `insufficient_data=true`; retry-collapse across every chunk per the original A4 measurement)
- `experiments/results/2026-04-16_phase-a4_genre-acquisition_raw.json` — W4-offset1800s-game-nochat (`insufficient_data=true`, 2/4 valid), W5-11688000-30min-olympics-nochat (`insufficient_data=false`, 3/3 valid; no platform_category field)
- `experiments/results/2026-04-16_phase-a4-acquisition-followup_raw.json` — W4f-offset1800s-12702452-chat (`insufficient_data=false`, 3/4 valid), W5f-11688000-30min-chat (`insufficient_data=false`, 3/3 valid)

Aggregation runner: `experiments/a4_aggregate_cross_session.py` loads `evaluate_global` from `experiments/a4_measure.py` via `importlib` and feeds merged cell summaries into a single pass. platform_category is named explicitly as the authoritative axis label per the acquisition-followup schema fix; cells lacking platform_category are counted in covered_cell_count via genre/insufficient_data but excluded from platform_category distinct-count.

Outputs (new, non-overwriting):

- `experiments/results/2026-04-16_phase-a4_cross-session-aggregation_raw.json`
- `experiments/results/2026-04-16_phase-a4_cross-session-aggregation.md`

Aggregated global:

- `covered_cell_count`: **3** (W4f, W5f, W5-olympics-nochat)
- `covered_lengths_min`: [30]
- `covered_genres`: [`game`, `olympics`]
- `covered_density_tiers`: [`high`, `medium`, `none`]
- `covered_platform_categories`: [`동계 올림픽`, `더 게임 오브 라이프 포 닌텐도 스위치`] (count=2; W5-olympics-nochat is unlabeled)
- `global_median_P95`: 3.2994
- `dispersion_range`: [2.8045, 3.7943]
- `dispersion_failures`: [`W5-11688000-30min-olympics-nochat`] (P95=4.6886 falls above 3.7943)
- `axis_coverage_ok`: **false** (needs covered_cell_count>=5 AND {30,60,180}⊆lengths; have 3 and {30} only)
- `dispersion_ok`: **false**
- `decision`: `per_cell_multiplicative`
- `recommended_margin`: null

Promotion gate (covered_cell_count>=5 AND covered_platform_category>=2 AND covered_density_tiers>=2 AND dispersion_ok): **FAIL**

- covered_cell_count: 3 (<5 FAIL)
- covered_platform_category_count: 2 (>=2 PASS)
- covered_density_tiers: 3 (>=2 PASS)
- dispersion_ok: false (FAIL)

Finding: the prior acquisition-followup seal framed aggregation as "{W1, W2, W3, W4f, W5f} = 5 valid cells if executed". Honest evaluate_global shows only 3 valid cells after aggregation — W1/W2/W3 are all `insufficient_data=true` in the committed 2026-04-15 A4 raw JSON because every chunk there exhibits the cache-warm retry-collapse pattern (initial pair also cache-hot, so user_attributable≈2 and user_ratio≈0.0003 on all 12 rows). Furthermore, pooling the no-chat W5 cell (P95=4.69) with chat-fed W4f/W5f (P95≈3.0) now violates dispersion. A4 promotion stays deferred.

## Step 1 — VOD selection

Chose `11688000` because:

- Cookies-gated download is already verified (144p mp4 present in sister `work/11688000/` from the acquisition-followup session; pipeline short-circuits download on existing file, so we still exercise the NetworkManager + cookies path for `get_video_info`).
- Chat API is cookieless and independently reproduced in the prior session.
- 144p artifact keeps disk/network cost bounded for a duration-limited smoke.
- Cell itself is already characterized (`W5f`, density medium, platform_category `동계 올림픽`) — known-good measurement neighborhood for smoke interpretation.
- 1800s limit is the same clip length used throughout A4 measurement, so the smoke exercises the same chunk-count regime without introducing new budget risk.

## Step 2 — full-pipeline smoke

Invocation (from sister worktree `C:/github/auto-caption-generator-main`):

```
python -m pipeline.main --process 11688000 --limit-duration 1800
```

Config used: `pipeline_config.json` copied from live (`C:/github/auto-caption-generator/pipeline_config.json`) into sister. File is `.gitignore`-covered in both worktrees (`git check-ignore pipeline_config.json` → PASS); no secret substring leaked to this document, the session packet, or summaries. No `pipeline_config.json` mutation on either side — the sister file is a read-through copy used only for the smoke run.

Runtime config values (unchanged from live):

- `chunk_max_chars`: 150000
- `chunk_overlap_sec`: 45
- `claude_timeout_sec`: 300
- `chunk_max_tokens`: not set (char-based fallback used)
- `auto_cleanup`: true

Per-stage result:

- VOD info lookup via `content.network.NetworkManager.get_video_info`: PASS.
- Download: SKIPPED (`이미 다운로드됨`) — artifact from prior session reused.
- Clip: `./work/11688000/..._144p_clip1800s.mp4` created.
- Chat collection: 1,600 raw → 1,544 after 1800s time filter; saved to `./work/11688000/11688000_chat.log`.
- Highlight analysis: 6 peaks from 176 buckets.
- Transcription: `./work/11688000/11688000_..._144p_clip1800s.srt` produced (Whisper large-v3-turbo + Silero VAD, runtime ~7-8 min on CUDA; progress-bar noise was written to stdout but the process exited 0 and the SRT is well-formed).
- SRT chunking: produced via `chunk_srt(max_chars=150000, overlap_sec=45, max_tokens=None, tokenizer_encoding='cl100k_base')` — char-based fallback.
- Claude summarization: per-chunk + merge completed within `claude_timeout_sec=300`.
- Report generation: Markdown + HTML + metadata JSON written.

Output locations:

- Markdown: `output/11688000_20260210_밀라노 올림픽 스노보드 같이 보자아 대한민국 유승은 선수 화이팅٩(●'▿'●)۶.md` (8,673 bytes)
- HTML: `output/11688000_20260210_밀라노 올림픽 스노보드 같이 보자아 대한민국 유승은 선수 화이팅٩(●'▿'●)۶.html` (25,604 bytes)
- Metadata: `output/11688000_20260210_밀라노 올림픽 스노보드 같이 보자아 대한민국 유승은 선수 화이팅٩(●'▿'●)۶_metadata.json` (886 bytes)
- Pipeline state: `output/pipeline_state.json` shows `processed_vods["11688000"]["status"]="completed"` and `completed_at=2026-04-16T05:23:58`.

Failure classification: N/A (run succeeded end-to-end).

## Step 3 — smoke verification

Artifact existence (all PASS):

- 144p mp4 in work/: PASS
- chat.log in work/: PASS
- clip1800s.srt in work/: PASS
- chunks produced (count observable in summarizer run): PASS
- Claude summary MD: PASS (well-formed Korean summary; Markdown parses cleanly)
- HTML: PASS (25,604 bytes)
- metadata JSON: PASS (video_no, title, duration=9463, category="동계 올림픽", total_chats=1544, 6 highlights, processed_at)

Regression check against smoke output (inline runner since `experiments/test_parser.py` and `experiments/test_html_render.py` hardcode VOD 12702452's output path, which does not exist in sister):

- `pipeline.summarizer._parse_summary_sections(md)`: title extracted, 5 hashtags, 13 timeline entries, 5 highlights, 2 editor-notes items.
- `pipeline.summarizer._generate_html(md, vod, highlights, chats, community_posts=[])`: rendered 20,676 chars, DOCTYPE present.
- PASS for the 4-file summarizer unit (`pipeline/summarizer.py` ↔ `prompts/청크 통합 프롬프트.md` ↔ `_parse_summary_sections()` ↔ `_generate_html()`).

## Promotion readiness — end-of-session

- `chunk_max_tokens` promotion: NOT performed. No `pipeline_config.json` mutation. No runtime-default change. Per-cell multiplicative stays the active decision.
- A4 axis coverage and dispersion gates both fail on cross-session aggregation. A4 promotion stays deferred pending (a) re-measurement of W1/W2/W3 without cache-warm retry-collapse, and (b) a decision on how to treat the no-chat W5 cell's dispersion outlier.

## Safety invariants held

- No `pipeline_config.json` mutation (sister copy is a read-through of the live file; its bytes equal live's bytes).
- No pipeline code edit.
- No runtime `chunk_max_tokens` default change.
- No overwrite of 2026-04-15 A4 raw/md (tracked, HEAD-identical).
- No overwrite of 2026-04-16 genre-acquisition raw/md (sister-only untracked carry-forward; kept as-is).
- No overwrite of 2026-04-16 acquisition-followup raw/md (sister-only untracked carry-forward; kept as-is).
- No live worktree write (smoke ran from sister cwd; outputs landed in sister `./output` and sister `./work`).
- No git ref mutation on either worktree.
- No remote push.
- No Chzzk cookie value printed to log, packet, state, or summaries.
- No edit to sealed session artifacts.
