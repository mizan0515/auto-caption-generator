# Session Summary — 2026-04-15-phase-a4-generalization-plan

- 세션 범위: Phase A4 — generalization measurement (length × genre × density matrix)
- 상태: converged (2026-04-15, Turn 7)
- 결과: **scoped PASS, global promotion blocked**

## 결론

- 최종 decision: **`per_cell_multiplicative`**
- per-cell margins:
  - **W1 = 3.37x** — 30min / talk / high (~76.17 msgs/min)
  - **W2 = 2.80x** — 1h / talk / medium (~38.08 msgs/min)
  - **W3 = 2.80x** — 3h / talk / low (~12.69 msgs/min)
- global promotion: **blocked** (아래 §blocker 참조)
- runtime 변경: **없음** — `pipeline/config.py:26 chunk_max_tokens=None` 그대로

## 핵심 수치

- 측정 규모: 3 cells × 4 chunks × (cold+warm) = **24 Claude 호출**, 총 비용 **$2.1566**
- raw 검증: 12 rows 전부 `consistency_pass=true` (deviation ∈ [0.000129, 0.000187], tolerance 0.03 내)
- additive overhead: **Δ ∈ [7,311, 7,817]**, median **7,620** — A3의 ~7.5k 재현
- CLI cache 상수: **cache_read = 20,668** on all 12 cold calls (A3와 동일)
- template_hash: `4d732b40fa470862` — `experiments/a4_measure.py` `make_template_hash()` (prefix-only SHA256[:16])
- per-cell aggregates:
  - W1: median_user_ratio=2.6983, P95=3.2008, median_additive=7,514
  - W2: median_user_ratio=2.4253, P95=2.6606, median_additive=7,604
  - W3: W2와 모든 집계값 완전 동일

## W2 ≡ W3 same-start-offset overlap

W2(1h)와 W3(3h)는 chunk_index 1–4 전체에 대해 `predicted / input / cache_creation / cache_read`가 **비트-단위 동일**하다. 원인: 두 clip이 같은 VOD의 t=0 시작점에서 길이만 다르게 잘렸기 때문에, chunker가 `chunk_max_chars=8000` 한도로 잘라낸 첫 4 chunk의 cue/chat payload가 완전히 같은 구간을 덮는다. 따라서 W3는 W2와 독립된 cell이 아니라 effective duplicate이며, A4의 실질 cell 수는 **2개**다.

## Global promotion blocker (C2 기준)

Covered cells = 3, 그러나 promotion rule을 세 곳에서 모두 실패:

1. **covered < 5** — C2는 최소 5 distinct cells 요구
2. **genres = 1 < 2** — `talk` 축만 측정, `game`/`reaction-or-music` 미측정
3. **dispersion_ok = false** — `global_median_P95 = 2.6606`, ±15% window `[2.2615, 3.0597]`. W1의 `P95 = 3.2008`은 상한을 벗어남

C2 decision tree 재도출 결과: `axis_coverage_ok=false ∧ dispersion_ok=false ⇒ per_cell_multiplicative`.
raw.json의 `recommended_margin = null` (global multiplicative 승급 차단), 운영자 제공 값은 per-cell margin 3종.

## 체크포인트 판정

- **C1 PASS** — 7개 live 앵커 모두 drift 없음 (`pipeline/config.py` 18-28, `pipeline/main.py` 187-196, `pipeline/chunker.py` 156-179 / 220-252, `pipeline/claude_cli.py` 23-41, `pipeline/summarizer.py` 59 / 121, `experiments/results/2026-04-15_phase-a3_token-margin-sampling.md` §5-§6).
- **C2 PASS** — Turn 6 독립 재계산이 decision `per_cell_multiplicative`을 raw.json과 동일하게 재현.
- **C3 PASS** — 12/12 rows 모두 row equation 재확인, deviation/user_attributable ∈ [0.000129, 0.000187].
- **C4 PASS** — per-cell/global aggregates 재계산이 result MD와 일치. n_valid_chunks=4 ≥ 3 규칙 충족.
- **C5 PASS** — codex-side auth는 Turn 6/Turn 7에서도 401 유지, claude-code가 execute 권한 보유. 본 세션에서는 이미 측정 완료 후였으므로 blocker 아님.

## 검증 결과

- Turn 6 codex가 `experiments/results/2026-04-15_phase-a4_raw.json` 으로부터 독립 재계산:
  - user_attributable_cold, additive_overhead, user_ratio
  - cache_read_delta, deviation, consistency_pass
  - median_user_ratio, P95_user_ratio (A3 small-n convention)
  - recommended_margin = ceil(P95 × 1.05 × 100)/100
  - axis_coverage, dispersion window, C2 decision
- 모든 값이 Turn 5 result MD / raw.json과 일치
- W2 ≡ W3 numerical equivalence는 pipeline 버그가 아니라 same-start-offset 방법론 한계임이 확인됨

## 후속 follow-up candidates

1. **genre-axis acquisition slice** — 같은 스트리머 talk 외 `game` 또는 `reaction-or-music` VOD 확보. downloader + Chzzk cookies 경로 필요. 성공 시 C2 genre 축 ≥2 조건 충족 및 추가 cell 확보로 global promotion 가능성 회복.
2. **`transcribe.py` split_video bug fix slice** — `-c copy` keyframe cut clip에서 `split_video() → extract_audio()` 조합이 degenerate part002 (261 bytes)를 생성해 ffmpeg이 실패. Turn 5에서는 `experiments/_a4_transcribe_wav.py` helper로 우회. 본 턴에서는 수정하지 않음. 별도 pipeline 픽스 세션으로 분리 권장.
3. **A4b start-offset diversification** — W2/W3 equivalence 문제를 해결하려면 같은 VOD 내에서도 disjoint start offset으로 샘플링하거나, 다른 VOD/스트리머로부터 cell을 확보해야 함.

## 운영 메모

- codex-side Claude CLI auth는 Turn 2/4/6 전부 **401** 지속. claude-code는 Turn 5에서 200 OK로 execute 완료.
- 본 세션은 raw artifact 검증 + 체크포인트 PASS 확인으로 닫혔다. code/config/result 숫자는 수정하지 않음.
- Phase label drift 메모: user의 A4 scope (generalization)는 progress_report.md의 원래 A3 정의와 일치, progress_report의 원래 A4는 "풀 파이프라인 종단 테스트". 본 세션은 user 레이블 유지. result MD §1에 drift note 포함.
