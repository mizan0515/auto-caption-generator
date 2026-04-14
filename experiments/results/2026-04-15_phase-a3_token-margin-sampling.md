# Phase A3 — tiktoken under-count margin sampling (single-sample multi-chunk)

- 측정일: 2026-04-14 KST
- 실행 주체: claude-code (Turn 5 execute)
- 세션: `2026-04-15-phase-a3-token-margin-sampling`
- 스코프: **30분 한국어 talk 단일 샘플 (Option B)** — 생성 가능한 유일한 local raw pair
- 원자료: `experiments/results/2026-04-15_phase-a3_raw.json`
- 측정 스크립트: `experiments/a3_measure.py` (신규, pipeline 코드 변경 없음)

---

## 1. Baseline anchors (live file:line, 재확인)

A3 Turn 1~4 에서 고정된 다섯 개 anchors 를 Turn 5 측정 직전 재확인. drift 없음.

| # | Anchor | 내용 |
|---|---|---|
| 1 | `pipeline/chunker.py:156-201` (`split_by_tokens`) | 각 cue `c.raw_block` 을 split 단위로 tokenize, `chunk_max_tokens` 초과 시 다음 chunk 시작 |
| 2 | `pipeline/main.py:191-197` | `max_tokens=cfg.get('chunk_max_tokens')` 가 `max_chars` 보다 우선 |
| 3 | `pipeline/config.py:23-27` (`DEFAULT_CONFIG`) | `chunk_max_tokens: 13200`, `chunk_tokenizer_encoding: "cl100k_base"` |
| 4 | `pipeline/claude_cli.py:23-58` (`_log_usage`) | 4-field 개별 로깅: `input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens` |
| 5 | `experiments/results/2026-04-15_phase-a2_token-chunking.md §5` | A2 단일 관측치: predicted 9,906 / user-attributable 17,850 / **1.80×** (prior expectation) |

---

## 2. Sample (Option B — single-sample multi-chunk)

Turn 3 에서 amendment A1 을 Option B 로 확정: cross-axis generalization 은 sample scarcity 때문에 차단하고, 로컬에 존재하는 유일한 raw pair 로 분포를 보는 방식.

| 항목 | 값 |
|---|---|
| SRT | `work/12702452/[탬탬버린] 7시 인생게임 (w. 지누,뿡,똘복) 인생에 프로란 없다. 모두 아마추어다._clip1800s.srt` |
| Chat log | `work/12702452/12702452_chat.log` |
| 길이 | 1,800 s (30 min) |
| Genre | Korean talk (multi-host chat) |
| chat density | **76.21 msgs/min** (high-density) |
| chunks 생성 | 5 (chunk_max_tokens=2500, overlap=30s, max_chars=150000 char-gate 불활성화) |
| highlights (find_edit_points) | 20 개 (top_n 기본값) |

**차단된 축** — 다음 축의 일반화는 A3 에서 선언적으로 차단되며, A3b 또는 A4 에서 acquisition-gated slice 로 다룬다:

- **길이 축**: 1h / 3h 샘플 없음 (로컬에 30min 만 존재)
- **장르 축**: 게임 / 리액션 / 음악 샘플 없음
- **밀도 축**: low-density (10 msgs/min 이하) 샘플 없음

---

## 3. Protocol

### 3.1 predicted_prompt_tokens 정의

`tiktoken.get_encoding("cl100k_base").encode(prompt)` 의 길이. `prompt` 는 `pipeline.summarizer._build_chunk_prompt(chunk, highlights, chats, vod)` 의 반환 문자열 전체 (instruction + chat_section + transcript).

### 3.2 Cold / Warm 페어링

각 chunk 당 두 번 호출:

1. **Cold** — `call_claude(prompt, timeout=300)` 1차. `cache_read_input_tokens` 에는 Claude CLI 자체 system prompt 캐시 (≈20,668) 만 포함되고, user prompt 는 `input_tokens + cache_creation_input_tokens` 로 들어감.
2. **Warm** — 동일 prompt 로 2s 이후 2차. 5분 cache TTL 안에 있으므로 `cache_creation_input_tokens ≈ 0`, user prompt 가 `cache_read_input_tokens` 로 이동.

### 3.3 user_ratio (authoritative metric)

```
user_attributable_cold = cold.input_tokens + cold.cache_creation_input_tokens
user_ratio             = user_attributable_cold / predicted_prompt_tokens
```

### 3.4 ±3% consistency check

```
cache_read_delta = warm.cache_read_input_tokens − cold.cache_read_input_tokens
tolerance        = user_attributable_cold × 0.03
deviation        = abs(cache_read_delta − user_attributable_cold)
PASS             <=> deviation <= tolerance
```

Cache 가 의도대로 동작했다면 warm 의 cache_read 증분은 cold 가 만든 cache_creation 과 거의 같아야 한다.

### 3.5 Rerun rule

첫 pair 가 ±3% 를 벗어나면 5s sleep 후 동일 prompt 로 cold/warm 재측정. 재측정도 벗어나면 `consistency_fail=true`, 해당 chunk 는 aggregate 에서 제외. (본 Turn 5 에서는 발동 안 됨.)

---

## 4. Per-chunk cold/warm 관측 (5/5 PASS)

| # | 구간 | cue | predicted | cold `input+cc` | cold `cache_read` | warm `cache_read` | Δcache_read | user_ratio | dev / tol | 판정 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| 1 | 00:00:17–00:09:45 | 54 | 3,394 | 10,705 | 20,668 | 31,371 | 10,703 | **3.1541** | 2 / 321.15 | ✓ |
| 2 | 00:09:20–00:16:29 | 53 | 6,285 | 13,905 | 20,668 | 34,571 | 13,903 | **2.2124** | 2 / 417.15 | ✓ |
| 3 | 00:16:04–00:23:09 | 53 | 3,402 | 10,810 | 20,668 | 31,476 | 10,808 | **3.1775** | 2 / 324.30 | ✓ |
| 4 | 00:22:44–00:28:07 | 45 | 6,564 | 14,285 | 20,668 | 34,951 | 14,283 | **2.1763** | 2 / 428.55 | ✓ |
| 5 | 00:27:43–00:30:21 | 21 | 3,419 | 10,887 | 20,668 | 31,553 | 10,885 | **3.1843** | 2 / 326.61 | ✓ |

**관측 상수**:

- 모든 cold call 의 `cache_read_input_tokens = 20,668` — Claude CLI 자체 system prompt 캐시. A2 §5 의 동일 숫자와 일치 (운영 환경 안정적).
- 모든 cold call 의 `input_tokens = 2` — prefix 토큰만 non-cached. 결정론적으로 cold/warm 에서 동일.
- 모든 warm call 의 `cache_creation_input_tokens = 0` — 2s 간격은 5분 cache TTL 내, cache 가 정상적으로 재활용됨.
- Δcache_read ≈ `user_attributable_cold` 오차 2 tokens (= cold 의 `input_tokens=2`) — cache 메커니즘이 user prompt 를 완전히 보존.

### 4.1 chunk 크기 vs user_ratio 산점도

| predicted bucket | user_ratio |
|---|---|
| 3,394 / 3,402 / 3,419 (~3.4k) | 3.15 ~ 3.18 (median 3.1775) |
| 6,285 / 6,564 (~6.4k) | 2.18 ~ 2.21 (median 2.1944) |
| **A2 참조**: 9,906 | 1.80 |

**핵심 관찰**: predicted 이 커질수록 user_ratio 는 단조 감소한다.

### 4.2 additive overhead 관점

| chunk | predicted | user_attributable | Δ = user_attrib − predicted |
|---|---:|---:|---:|
| 1 | 3,394 | 10,705 | 7,311 |
| 2 | 6,285 | 13,905 | 7,620 |
| 3 | 3,402 | 10,810 | 7,408 |
| 4 | 6,564 | 14,285 | 7,721 |
| 5 | 3,419 | 10,887 | 7,468 |
| A2 참조 | 9,906 | 17,850 | 7,944 |

Δ 의 mean ≈ **7,579 tokens** (A3 5개), A2 참조 7,944 포함시 mean ≈ 7,640, std ≈ 220 — **추가 overhead 가 chunk 크기와 무관하게 ~7.5k 로 거의 상수**. 이는 tiktoken ↔ Claude tokenizer 의 배수 불일치가 아니라 **prompt 상 보이지 않는 Claude 측 상수 overhead (CLI 가 덧붙이는 wrapper/tool prelude 류 추정) + 한국어 under-count 의 혼합**임을 시사한다.

---

## 5. Aggregation

```
ratios_sorted            = [2.1763, 2.2124, 3.1541, 3.1775, 3.1843]
n_chunks_total           = 5
n_chunks_valid           = 5
consistency_fail_count   = 0  (0% <= 25%)
sample_median_user_ratio = 3.1541
global_p95_user_ratio    = 3.1843    # small-n 이므로 P95 = max (contract 의 small-n 규칙)
recommended_margin       = ceil(3.1843 * 1.05 * 100) / 100 = 3.35
chat_density_msgs_per_min = 76.21
```

Turn 3 contract C4 의 FAIL 조건 3 개 재검정:

| FAIL 조건 | 임계 | 실측 | 판정 |
|---|---|---|---|
| (i) n_chunks_valid < 3 | < 3 | **5** | PASS |
| (ii) > 25% 가 ±3% 실패 | > 25% | **0%** | PASS |
| (iii) single-axis-only generalization-blocked | scope 선언 필수 | 30-min Korean talk 로 선언, 길이/장르/밀도 축 차단 명시 | **scoped PASS** (recommendation 유효, but 축 한정) |

---

## 6. Decision

### 6.1 Recommended margin

**본 scope (30-min Korean talk, ~76 msgs/min high-density) 에서 tiktoken cl100k_base 예측 대비 user-attributable 상한은 3.35×.**

A2 의 provisional 1.80× 는 **prior expectation 으로 강등** (Turn 3 C4). A3 측정으로 실제 분포가 드러났으며 1.80× 는 predicted≈10k 대역의 특수해였음이 확인됨.

### 6.2 A2 sanity comparison (same pipeline, same prompt builder)

| 자료 | predicted | user_attributable | ratio | Δ(addi) |
|---|---:|---:|---:|---:|
| A2 §5 (단일) | 9,906 | 17,850 | 1.80 | 7,944 |
| A3 chunk 4 | 6,564 | 14,285 | 2.18 | 7,721 |
| A3 chunk 2 | 6,285 | 13,905 | 2.21 | 7,620 |
| A3 chunk 5 | 3,419 | 10,887 | 3.18 | 7,468 |
| A3 chunk 3 | 3,402 | 10,810 | 3.18 | 7,408 |
| A3 chunk 1 | 3,394 | 10,705 | 3.15 | 7,311 |

**ratio 는 chunk 크기에 역비례, Δ(addi) 는 ≈ 상수**. 같은 pipeline 의 같은 prompt 빌더에서 두 실험이 모순 없이 정렬된다.

### 6.3 운영 적용 (두 가지 식, 상황별 선택)

1. **Multiplicative (보수적, small chunk 포함 안전):**
   `claude_budget ≈ predicted_tiktoken × 3.35 + CLI_system_prompt_cache(≈20,668)`
   - 장점: 구현 단순 (한 배수)
   - 단점: predicted ≥ 6k 대역에서 2~3k 토큰 과잉 예산

2. **Additive (더 정확, 관측치 반영):**
   `claude_budget ≈ predicted_tiktoken × 1.0 + 7,800 (additive_overhead) + 20,668 (CLI_cache)`
   - 장점: chunk 크기에 관계없이 ±400 tokens 이내 적중
   - 단점: additive_overhead 는 prompt 구조 변경 (`_build_chunk_prompt` instruction/chat_section 포맷 변경) 시 재측정 필요

A3 는 **두 식을 나란히 제안**한다. pipeline 기본 정책은 일단 **multiplicative 3.35×** 를 권장 (Turn 3 C4 가 margin 을 하나의 스칼라로 요구). additive 식은 후속 phase (A3b 또는 A4) 에서 `chunk_max_tokens` 계산 공식을 재설계할 때 채택 후보로 기록.

### 6.4 Scope 한계 (강조)

본 recommendation 은 **다음 축에서만** 유효:

- 길이: 30 min
- 장르: Korean talk
- chat density: ~76 msgs/min (high)
- prompt 구조: 현재 `_build_chunk_prompt()` (instruction 500-600 tokens + chat_section + transcript)

추가 축 확장은 A3b (length expansion), A4 (genre/density expansion) 에서 acquisition-gated 로 수행한다. 본 MD 의 3.35× 를 1h/3h 또는 game/reaction 장르에 그대로 적용하지 말 것.

### 6.5 Pipeline 반영 여부

- **이번 turn 에서는 pipeline 코드를 변경하지 않는다** (Turn 3 C4 + 사용자 지시: "code changes forbidden").
- `pipeline/config.py:23-27` 의 `chunk_max_tokens: 13200` 은 A2 의 1.80× 전제로 계산된 값. 3.35× 기준으로 재계산하면 target_claude_budget 30k 의 경우 `chunk_max_tokens ≈ (30,000 − 20,668 − 7,800) / 1.0 = 1,532` (additive) 혹은 `(30,000 − 20,668) / 3.35 ≈ 2,786` (multiplicative) 로 현재보다 훨씬 작아야 함. **이 config 수정은 A3b/A4 의 scope 확정 이후** — 지금 config 를 바꾸면 scope-limited 결과를 전체 운영에 일반화하는 것이 되어 Turn 3 C4 (iii) 에 위배.
- 후속 phase 에서 config 수정을 제안할 때 본 MD §6.3 의 두 식 중 하나를 채택.

---

## 7. 재현 경로

```
PYTHONPATH=. python -X utf8 experiments/a3_measure.py
# → experiments/results/2026-04-15_phase-a3_raw.json
```

- 실행 시간: ~7 min (10 calls: 5 cold + 5 warm)
- 총 비용: ≈ $0.85 (raw.json 의 `total_cost_usd` 합계)
- Python: `pipeline.chunker.chunk_srt`, `pipeline.summarizer._build_chunk_prompt`, `pipeline.chat_analyzer.find_edit_points`, `pipeline.claude_cli.call_claude`, `pipeline.models.VODInfo` 만 import — pipeline 코드 미수정
