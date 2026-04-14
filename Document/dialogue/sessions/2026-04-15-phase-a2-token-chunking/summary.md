# Session Summary — 2026-04-15-phase-a2-token-chunking

- 세션 범위: Phase A2 — token-based chunking 도입과 same-source 비교 실험
- 상태: `converged` (2026-04-14, Turn 5)
- 브랜치: codex/phase-a1-token-logging

## 합의된 변경

- `pipeline/config.py`
  - `chunk_max_tokens`, `chunk_tokenizer_encoding` 추가
  - precedence: `chunk_max_tokens > chunk_max_chars`
  - Turn 5 에서 DEFAULT_CONFIG / json merge / main.py fallback / both-set 설명 주석 보강
- `pipeline/main.py`
  - chunk 호출 fallback 을 `chunk_max_chars=8000`, `chunk_overlap_sec=30` 으로 정렬
  - `max_tokens=cfg.get("chunk_max_tokens")`, `tokenizer_encoding=cfg.get("chunk_tokenizer_encoding", "cl100k_base")` 전달
- `pipeline/chunker.py`
  - `split_by_tokens()` 추가
  - char/token 경로 모두 per-cue `raw_block` 기준 계량
  - overlap rewind 로직 동일 유지
  - 모듈 docstring 에 raw_block vs cues_to_txt 단위 차이 명시
- `experiments/results/2026-04-15_phase-a2_token-chunking.md`
  - tokenizer 3후보 × 6축 비교표
  - baseline_150k/chunk_15k/chunk_8k/chunk_5k/token_4000/token_2500 same-source 표
  - C5 실측: predicted 9,906 vs observed sum 38,518
- `experiments/results/progress_report.md`, `PROJECT-RULES.md`
  - A1/A2 완료 상태와 결과 링크로 동기화

## 체크포인트 결과

| ID | 결과 | 근거 |
|----|------|------|
| C1 | PASS | §2 표가 세 후보 × 여섯 축을 모두 채우고, 선정 근거가 오프라인 + 라이선스 + 속도 세 조건을 명시함 |
| C2 | PASS | config/main live 코드와 REPL 3케이스(legacy-only=2, token-only=3, both-set=5) 재현 완료 |
| C3 | PASS | `split_by_tokens()` 는 `c.raw_block` 만 토큰화, overlap rewind 는 char path 와 동일, `split_by_chars()` diff 무회귀 확인 |
| C4 | PASS | §4.2 표 완비, §4.3 의 13,402 / 8,446 = 1.5868x 설명 확인, sample row 독립 재측정으로 핵심 수치 일치 |
| C5 | PASS | 산술 검증 완료 (`38,518`, `+28,612`, `3.89x`), codex-side 401 blocker 는 A1 과 일관된 환경 이슈로 기록 |

## 핵심 증빙

- 독립 재현 청크 수:
  - legacy-only (`max_chars=8000`) → 2
  - token-only (`max_tokens=4000`) → 3
  - both-set (`max_chars=8000`, `max_tokens=2500`) → 5
- 독립 재측정 ratio:
  - `sum(rb_chars)=13,402`
  - `sum(txt_chars)=8,446`
  - `rb/txt = 1.5868x`
- codex-side Claude auth probe:
  - `claude -p --output-format json --max-turns 1` → `authentication_error` 401, usage 0
- Validator:
  - `tools/Validate-Documents.ps1 -Root . -IncludeRootGuides -IncludeAgentDocs`
  - `tools/Validate-DadPacket.ps1 -Root . -AllSessions`

## 운영 결정

1. `chunk_max_tokens` 는 opt-in 이며 기본값은 `None` 이다.
2. token path 는 prompt 전체가 아니라 transcript(raw_block) 예산을 자른다.
3. 한국어 SRT 기준 `tiktoken cl100k_base` 는 Claude 실 usage 대비 과소추정 경향이 있어, 현재는 약 `1.8x` 여유 규칙을 임시 운영값으로 둔다.
4. Claude CLI `cache_read_input_tokens` 는 CLI/system prompt 캐시이므로 비용·예산 해석에서 user prompt 기여분과 분리해서 봐야 한다.

## 다음 세션

Phase A3 — 장르/길이 확대 재측정 + `chunk_max_tokens` 운영 권고 구체화. 새 DAD 세션에서 시작.
