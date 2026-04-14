# Phase A4 — 토큰 마진 일반화 측정 (3 cells, length-axis)

**status**: scoped PASS — `per_cell_multiplicative` (global multiplicative 불가, axis coverage 미충족)
**measured_at**: 2026-04-15
**owner**: claude-code (codex-side auth 401 지속, C5 규칙 적용)
**session**: Document/dialogue/sessions/2026-04-15-phase-a4-generalization-plan/
**contract**: C1~C5 accepted (Turn 3), MAX_CHUNKS_PER_CELL=4 cost-cap 추가 (Turn 5)
**raw**: experiments/results/2026-04-15_phase-a4_raw.json
**predecessor**: experiments/results/2026-04-15_phase-a3_token-margin-sampling.md (3.35x, Δ≈7.5k)

---

## §1. 맥락 & phase label drift

A3은 단일 셀 `(30min, talk, high≈76.21)`에서 `recommended_margin=3.35x` + additive Δ≈7.5k을
scoped PASS로 확정했다. A4는 생성기 cfg를 3.35x로 승격할 수 있는지 판단하기 위해 **3×3
일반화 매트릭스** (length × genre × density)의 cell-coverage와 dispersion을 측정한다.

**Phase label drift 메모**: `experiments/results/progress_report.md`의 원래 A3 정의는
"30min/1h/3h 각 1샘플" 생성이었고 A4는 "풀 파이프라인 종단 테스트"였다. 본 세션은 사용자
지시에 따라 A4=일반화로 label을 유지하되, 이 drift는 별도 문서 동기화 턴에서 해소한다.

## §2. C1 baseline anchors (re-read in Turn 5 opening)

Turn 5 opening에서 7개 live anchor를 재확인했고 드리프트 없음:

- `pipeline/config.py:9-41` — `DEFAULT_CONFIG.chunk_max_tokens=None`, `chunk_max_chars=8000`, `chunk_tokenizer_encoding="cl100k_base"`, `chunk_overlap_sec=30` (A3 상태 유지)
- `pipeline/main.py:186-197` — `chunk_srt(srt_path, max_chars, overlap_sec, max_tokens, tokenizer_encoding)` 5-arg 호출
- `pipeline/chunker.py:156-201` — `split_by_tokens()` per-cue `raw_block` token_count_cache + rewind
- `pipeline/chunker.py:204-257` — `chunk_srt()` dispatcher (`if max_tokens is not None` 분기)
- `pipeline/claude_cli.py:23-58` — `_log_usage()` 4-field emit + empty guard
- `pipeline/summarizer.py:59,121` — `_build_chunk_prompt(chunk, highlights, chats, vod_info)` 서명 + 호출 위치
- `experiments/results/2026-04-15_phase-a3_token-margin-sampling.md` §5~§6 — 3.35x + Δ≈7.5k

**런타임 승격 없음**: `pipeline/config.py:26 chunk_max_tokens=None`은 본 턴에서도 변경되지
않는다. A3의 3.35x는 A4 결과와 무관하게 scoped finding 상태를 유지한다 (C2 promotion rule
미충족 — 아래 §6 참조).

## §3. 샘플 획득 (acquisition slice)

| cell | 획득 방식 | 경로 |
| --- | --- | --- |
| W1 (30min) | 기존 A3 SRT 재사용 | `work/12702452/..._144p_clip1800s.srt` (22,402 bytes) |
| W2 (1h)   | ffmpeg `-c copy` 0~3600s 컷 → wav 추출 → Whisper | `..._clip3600s.srt` (47,111 bytes, 334 entries) |
| W3 (3h)   | ffmpeg `-c copy` 0~10800s 컷 → wav 추출 → Whisper | `..._clip10800s.srt` (131,253 bytes, 986 entries) |

Whisper 실행 메모:
- `transcribe.py`의 내장 `split_video()` + `extract_audio()` 경로가 `-c copy` 컷된 클립에서
  degenerate 261-byte part002 mp4를 만들어 ffmpeg 오디오 추출이 실패했다.
- 우회: `experiments/_a4_transcribe_wav.py` 보조 스크립트가 `load_models()` + `load_audio()`
  + `get_speech_segments()` + `transcribe_audio()`를 직접 호출하고 split/extract 단계를
  건너뛴다. 파이프라인 파일은 수정하지 않았다.
- 모델: `openai/whisper-large-v3-turbo` on RTX 2070 Super (CUDA). 1h 전사 330.7s,
  3h 전사 964.4s (합계 ~22min).

**채팅 로그 범위 주의**: `12702452_chat.log`는 0-1799s만 커버한다 (max_sec=1799,
count=2285). 따라서 W2/W3의 "cell-level chat density"는 낮아지지만 (W2 38.08, W3 12.69),
chunk-level prompt에 포함되는 채팅은 여전히 첫 30분 구간에서만 필터된다. 이 제약은 §6의
per-cell 비교 해석에서 핵심이다.

## §4. 측정 프로토콜

A3 C3 프로토콜을 변경 없이 적용:
- `chunk_srt(..., max_tokens=2500, tokenizer_encoding="cl100k_base", overlap_sec=30)`
- Cold/warm paired `claude -p --output-format json` 호출, `_log_usage` 4-field 파싱
- `user_attributable_cold = input_tokens + cache_creation_input_tokens`
- `cache_read_delta = warm.cache_read - cold.cache_read`
- Consistency: `|cache_read_delta - user_attributable| ≤ user_attributable * 0.03`
- `user_ratio = user_attributable / predicted_prompt_tokens` (tiktoken cl100k_base 재인코딩)
- `additive_overhead = user_attributable - predicted_prompt_tokens`

A4 추가 요소:
- `template_hash`: `_build_chunk_prompt`의 transcript 이전 prefix를 `sha256[:16]`으로 캡처
  (probe title="template-hash-probe", dummy chunk/vod) → `4d732b40fa470862`. A3의 `Δ≈7.5k`
  상수가 동일 template 가정 하에서 유효함을 재현 가능한 방식으로 고정.
- `MAX_CHUNKS_PER_CELL=4` cost-cap: `measure_cell()`이 `chunk_srt()` 결과의 앞 4개만 측정.
  C4의 `n_valid_chunks ≥ 3` 기준을 여유 있게 충족하면서 3 cells × 4 chunks × 2 calls
  = 24 Claude 호출로 제한 (실제 비용 $2.1566).
- `CELLS`는 `experiments/_a4_cells.json`에서 runtime 로드 (Unicode 경로를 Python 소스에
  직접 쓰지 않기 위함). paths JSON은 `experiments/_a4_paths.json`에서 live filesystem
  resolve로 생성.

## §5. 측정 결과

### §5.1 Per-chunk (raw)

모든 12개 chunk가 consistency pass (deviation ≤ tolerance). `cache_read_input_tokens` 콜드
값은 **전 12건 모두 20,668**로 고정 — A3의 CLI system-prompt 캐시 상수가 A4에서도 재현됨.

| cell | chunk | predicted | user_attr | user_ratio | additive | pass |
| --- | --- | --- | --- | --- | --- | --- |
| W1-30min-talk-high | 1 | 3,358 | 10,669 | 3.1772 | 7,311 | ✓ |
| W1-30min-talk-high | 2 | 6,249 | 13,869 | 2.2194 | 7,620 | ✓ |
| W1-30min-talk-high | 3 | 3,366 | 10,774 | 3.2008 | 7,408 | ✓ |
| W1-30min-talk-high | 4 | 6,528 | 14,249 | 2.1828 | 7,721 | ✓ |
| W2-1h-talk-medium | 1 | 4,467 | 11,885 | 2.6606 | 7,418 | ✓ |
| W2-1h-talk-medium | 2 | 6,310 | 13,957 | 2.2119 | 7,647 | ✓ |
| W2-1h-talk-medium | 3 | 4,614 | 12,175 | 2.6387 | 7,561 | ✓ |
| W2-1h-talk-medium | 4 | 7,651 | 15,468 | 2.0217 | 7,817 | ✓ |
| W3-3h-talk-low | 1 | 4,467 | 11,885 | 2.6606 | 7,418 | ✓ |
| W3-3h-talk-low | 2 | 6,310 | 13,957 | 2.2119 | 7,647 | ✓ |
| W3-3h-talk-low | 3 | 4,614 | 12,175 | 2.6387 | 7,561 | ✓ |
| W3-3h-talk-low | 4 | 7,651 | 15,468 | 2.0217 | 7,817 | ✓ |

### §5.2 Per-cell aggregate

| cell | density (msgs/min) | n_chunks_full / cap / valid | median_ratio | **P95_ratio** | median_additive | per-cell `ceil(P95*1.05*100)/100` |
| --- | --- | --- | --- | --- | --- | --- |
| W1-30min-talk-high   | 76.1667 | 5 / 4 / 4 | 2.6983 | **3.2008** | 7,514.0 | **3.37** |
| W2-1h-talk-medium    | 38.0833 | 10 / 4 / 4 | 2.4253 | **2.6606** | 7,604.0 | **2.80** |
| W3-3h-talk-low       | 12.6944 | 27 / 4 / 4 | 2.4253 | **2.6606** | 7,604.0 | **2.80** |

### §5.3 Global aggregate

- `covered_cell_count`: 3 (모든 셀 `n_valid_chunks ≥ 3`, insufficient-data 없음)
- `covered_lengths_min`: [30, 60, 180] — ✓ 3 length buckets
- `covered_genres`: ["talk"] — ✗ 1 genre (요구 ≥2)
- `covered_density_tiers`: ["high", "low", "medium"] — 명목상 3 tiers
- `global_median_P95`: 2.6606 (even-n 2개 중앙값의 평균; P95s = [2.6606, 2.6606, 3.2008])
- `dispersion_range` (±15%): [2.2615, 3.0597]
- `dispersion_failures`: ["W1-30min-talk-high"] (P95=3.2008 > 3.0597)
- `axis_coverage_ok`: **false** (≥5 cells × 2 genres × 2 density 조건 미충족)
- `dispersion_ok`: **false** (W1 범위 초과)

## §6. 결정 (C2/C4 4-way decision)

C4에 사전등록된 4개 결과 중 **`per_cell_multiplicative`** 채택. 근거:

| rule | 조건 | status |
| --- | --- | --- |
| global_multiplicative | axis_coverage_ok AND dispersion_ok | ✗ (coverage/dispersion 모두 실패) |
| global_additive | covered≥5 AND genres≥2 AND tiers≥2 | ✗ (covered=3, genres=1) |
| **per_cell_multiplicative** | covered≥1 | ✓ (3 cells) |
| scope_blocked | not covered | — |

### §6.1 per-cell 권장치

- `(30min, talk, high≈76.17)`: **3.37x** (A3의 3.35x와 오차 ±0.02 범위 내 재현)
- `(1h,   talk, medium≈38.08)`: **2.80x**
- `(3h,   talk, low≈12.69)`: **2.80x**

### §6.2 W2 ≡ W3 방법론적 한계 (중요)

W2와 W3의 per-cell P95/median/additive이 수치적으로 **완전히 동일**하다. 이는 버그가 아니라
측정 설계의 의도치 않은 결과다:

- W2(1h SRT)와 W3(3h SRT)는 모두 동일 full-VOD의 t=0부터 시작한 Whisper 전사본이다.
  첫 4 chunk (≈앞 15-25분 구간) 는 VAD + Whisper 결정론성에 의해 토큰 단위로 일치했다.
- chat_log가 0-1799s만 커버하므로 per-chunk chat filtering도 동일 시간창 → 동일 chats.
- 결과: W2의 첫 4 chunks ≡ W3의 첫 4 chunks (prompt tokens, predicted, user_attr 전부 동일).

C2의 "≥2 density tiers" 조건은 명목상 W2(medium)·W3(low)·W1(high)로 3개지만, **독립 측정
관점에서는 실질적으로 2개 셀**(W1, W2=W3)에 해당한다. 이는 length-axis-only 확장 + 같은
VOD 재사용 전략의 근본 한계를 드러낸다. 이후 A4 확장 시 **서로 다른 시작 오프셋** 또는
**다른 VOD**를 샘플링해야 density tier 효과를 실제로 측정할 수 있다.

### §6.3 additive overhead 재현

A3의 `Δ≈7.5k` 상수가 A4 12행 전체에서도 재현:
- min/median/max = 7,311 / 7,620 / 7,817 (range 506 tokens, ±3.4% of median)
- W1/W2/W3 cell 단위 median additive = 7,514 / 7,604 / 7,604

CLI system-prompt cache는 전 12행에서 `cache_read_input_tokens=20,668` 상수로 관측됨 →
additive form 권장치 `Δ≈7,600 + 20,668 ≈ 28,300` 토큰 상수 오버헤드 (A3의 `+~7,800 + 20,668`
재현 범위 내).

### §6.4 런타임 cfg 결정

**`pipeline/config.py:26 chunk_max_tokens=None` 유지.** A3의 3.35x도 A4의 3.37x도 런타임
default로 승격하지 않는다. 근거:
- C2 promotion rule 미충족 (covered ≥5 AND genres ≥2 AND dispersion ok 모두 실패)
- 실질적 셀 수 2개 (W1, W2≡W3) — length-axis 확장의 정보량 한계
- genre 축 확장은 여전히 pipeline.downloader + Chzzk 쿠키 경로를 요구 (이번 턴에서는
  cookie boolean=True만 확인, 유효성은 미검증)

## §7. 재현 경로

```powershell
# 1) 세션/계약 재확인
Get-Content Document\dialogue\state.json
Get-Content Document\dialogue\sessions\2026-04-15-phase-a4-generalization-plan\state.json

# 2) C1 anchor 재확인 (read-only)
# pipeline/config.py:9-41, main.py:186-197, chunker.py:156-257, claude_cli.py:23-58,
# summarizer.py:59,121, A3 결과 MD §5-§6

# 3) acquisition (이미 수행됨; 재실행 시 기존 파일 덮어쓰기)
ffmpeg -ss 0 -t 3600  -i "work/12702452/..._144p.mp4" -c copy "..._clip3600s.mp4"
ffmpeg -ss 0 -t 10800 -i "work/12702452/..._144p.mp4" -c copy "..._clip10800s.mp4"
# wav 추출:
ffmpeg -i "..._clip3600s.mp4"  -vn -acodec pcm_s16le -ar 16000 -ac 1 "..._clip3600s.wav"
ffmpeg -i "..._clip10800s.mp4" -vn -acodec pcm_s16le -ar 16000 -ac 1 "..._clip10800s.wav"
# 전사 (split/extract 우회):
python -X utf8 experiments/_a4_transcribe_wav.py <wav_1h> <srt_1h> <wav_3h> <srt_3h>

# 4) CELLS 생성 + 측정
# experiments/_a4_paths.json, _a4_cells.json 이 live filesystem 재해석 결과로 생성됨
python -X utf8 experiments/a4_measure.py
# → experiments/results/2026-04-15_phase-a4_raw.json 갱신

# 5) validator
powershell -File tools/Validate-Documents.ps1 -Root . -IncludeRootGuides -IncludeAgentDocs
powershell -File tools/Validate-DadPacket.ps1 -Root . -AllSessions
```

비용 실측: **$2.1566 over 24 Claude calls** (Turn 4 예측 $2.5~3.0 범위 내).

## §8. 열린 리스크 / follow-up

1. **genre 축 단일** — global multiplicative 승격을 위해서는 `(game, *)` 또는
   `(reaction/music, *)` 셀이 필요. 현재 로컬 자산만으로는 불가능하며 pipeline.downloader
   경로 활용이 필수. 쿠키 유효성 실측이 선행되어야 함.
2. **W2≡W3 등가성** — 같은 VOD의 t=0 시작 전사본은 length-axis 확장이 아니라 "label
   확장"에 가깝다. 다음 A4 iteration에서는 서로 다른 start offset 또는 다른 VOD에서 셀을
   뽑아야 density 효과가 실측됨.
3. **`template_hash=4d732b40fa470862`** — A3 raw에는 이 필드가 없지만 pipeline/summarizer.py
   가 Turn 2/3/4/5에 걸쳐 수정되지 않았음을 C1 re-audit으로 확인했으므로 A3의 Δ≈7.5k은
   동일 hash 하에서 관측된 것과 동등. 향후 `_build_chunk_prompt` 템플릿이 변경되면 hash가
   바뀌어 additive 상수가 자동 무효화됨.
4. **phase label drift** — progress_report.md의 A3/A4 label과 현재 세션의 A3/A4 scope
   정의가 어긋나 있음. 별도 doc-sync 턴에서 해소 예정.
