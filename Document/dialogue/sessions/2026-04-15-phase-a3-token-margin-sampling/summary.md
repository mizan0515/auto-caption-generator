# Session Summary — 2026-04-15-phase-a3-token-margin-sampling

- 세션 범위: Phase A3 — token margin sampling
- 상태: converged (2026-04-14, Turn 6)
- 결과: **scoped PASS**

## 결론

- 추천 margin: **3.35x**
- 적용 범위: **30분 Korean talk / high-density chat (~76.21 msgs/min)** 단일 샘플
- 일반화 상태: **blocked**
  - 길이 축(1h/3h), 장르 축(game/reaction/music), 밀도 축(low/medium)은 미측정

## 핵심 수치

- raw JSON 재검산:
  - ratios_sorted = [2.1763, 2.2124, 3.1541, 3.1775, 3.1843]
  - median = 3.1541
  - P95 = 3.1843
  - recommended margin 계산 결과는 **3.35**였다 (ceil(P95 × 1.05 × 100)을 100으로 나눈 값)
- consistency:
  - n_chunks_valid = 5
  - consistency_fail_count = 0
  - 5개 chunk 모두 deviation = 2, tolerance = 321.15~428.55 범위 내
- additive overhead:
  - A3 5개만 기준 Δ mean = **7,505.6**, population std = **147.2**
  - A2 참조 1개 포함 Δ mean = **7,578.7**, population std = **211.5**

## 해석

A2의 1.80x 와 A3의 3.35x 는 서로 모순이 아니라, 작은 predicted 구간에서 ratio가 커지고 실제 차이는 약 7.5k 부근의 additive overhead로 설명된다는 점에서 하나의 이야기로 정렬된다. 따라서 이번 세션의 output은 “범용 1.8x 확인”이 아니라 “현재 샘플 클래스에서의 운영 상한 3.35x”로 해석해야 한다.

## 검증 결과

- Turn 6 codex가 experiments/results/2026-04-15_phase-a3_raw.json 으로부터 다음을 독립 재계산:
  - user_attributable_cold
  - cache_read_delta
  - deviation, tolerance
  - user_ratio
  - median, P95, recommended_margin
  - additive overhead mean/std
- 모든 값이 Turn 5 문서와 일치
- scope 문구도 experiments/results/2026-04-15_phase-a3-token-margin-sampling.md §2, §6.4 에 명시됨

## 운영 메모

- codex-side claude CLI auth는 Turn 6에서도 **401** 이었다.
- 본 세션은 raw artifact 검증으로 닫았으므로, auth blocker가 close 자체를 막지는 않는다.
- 후속 확장은 **새 세션(A3b/A4)** 에서 length/genre/density 샘플 확보 후 진행.
