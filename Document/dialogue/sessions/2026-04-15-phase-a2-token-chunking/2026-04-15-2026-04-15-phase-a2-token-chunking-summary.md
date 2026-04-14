# 2026-04-15-phase-a2-token-chunking — Closeout

Phase A2 는 Turn 5 codex peer verification까지 마치고 `converged` 로 종료했다.

- 코드 결과:
  - `chunk_max_tokens` / `chunk_tokenizer_encoding` 도입
  - precedence 는 `chunk_max_tokens > chunk_max_chars`
  - token/char 경로 모두 `Cue.raw_block` 기준으로 split
- 실험 결과:
  - same-source 비교표 6 config 완료
  - `raw_block` vs `cues_to_txt` 단위 차이: `13,402 / 8,446 = 1.5868x`
  - C5 실측 문서값 산술 확인: `9,906 -> 38,518`, `Δ=+28,612`, `3.89x`
- peer verification:
  - legacy-only / token-only / both-set 청크 수를 codex 측에서 `2 / 3 / 5` 로 독립 재현
  - codex-side Claude auth probe 는 여전히 401 이었지만, 이는 A1 부터 이어진 환경 blocker 로 기록되며 A2 코드 회귀 증거는 아님
- 문서 동기화:
  - `experiments/results/progress_report.md`
  - `PROJECT-RULES.md`
  - `pipeline/config.py` 주석

후속 범위는 Phase A3 새 세션이다. 핵심 과제는 한국어/장르/길이별 token under-count 계수 재측정과 운영 기본값 구체화다.
