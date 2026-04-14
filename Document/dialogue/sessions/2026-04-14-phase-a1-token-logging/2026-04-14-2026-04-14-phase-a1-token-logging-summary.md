# 2026-04-14 Phase A1 — Claude CLI Token Usage Logging (Closed)

- Session ID: `2026-04-14-phase-a1-token-logging`
- 상태: `converged`
- 종료일: 2026-04-14 (KST)
- 브랜치: codex/phase-a1-token-logging
- 턴 수: 4 (codex → claude-code → codex → claude-code)

## 목표

`experiments/results/progress_report.md` Phase A/1 항목 — 모든 Claude CLI 호출이 응답 `usage` 를 파싱하여 `input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens` 를 구조화된 로그로 남기도록 한다.

## 결과 요약

- `pipeline/claude_cli.py` 에 `_log_usage(payload)` 헬퍼 신설.
- `_parse_claude_output()` 성공 경로(dict / list result) 두 분기에만 연결; 에러·빈 응답·JSONDecodeError 폴백 경로는 건드리지 않음.
- `call_claude()` 와 `call_claude_with_context()` 가 공유하는 파서 단일 지점 수정으로 두 엔트리포인트 동시 커버.
- 실제 Claude 백엔드 호출 4회(Turn 2 2회 + Turn 4 2회) 모두에서 `Claude usage input_tokens=... output_tokens=... cache_creation_input_tokens=... cache_read_input_tokens=... session_id=... total_cost_usd=...` INFO 로그 관찰.

## 체크포인트

| ID | 설명 | 결과 |
|----|------|------|
| C1 | `pipeline/claude_cli.py` usage 파싱, result/error 무회귀 | PASS |
| C2 | 성공 호출 시 input/output/cache 토큰 구조화 로그 | PASS |
| C3 | `experiments/results/2026-04-14_phase-a1_token-logging.md` before/after + 결정 근거 | PASS |
| C4 | 실 Claude 호출 1회 이상으로 리포지토리 환경에서 확인 | PASS |

## 주요 결정

1. 로그 레벨 `INFO` — 운영 로그(`output/logs/`) 기본 수집 레벨이며, 비용 감사와 회귀 추적에 쓰이므로 DEBUG 로 숨기지 않는다.
2. `cache_*` 필드는 `isinstance(value, (int, float))` 로 검사 — zero-valued 필드도 누락 없이 기록 (Turn 4 에서 `cache_creation_input_tokens=0` 케이스 실관측).
3. 에러 경로와 텍스트 폴백 경로에는 로그 남기지 않음 — 기존 예외 동작 보존.
4. Turn 3 amendment(codex 401 로 수렴 보류) 는 Turn 4 에서 **superseded** — C4 는 "본 리포지토리 환경" 기준이며, 환경 크리덴셜은 세션 밖 문제.

## 산출물

- 코드: `pipeline/claude_cli.py` (+58/-5 diff)
- 실험 결과 문서: `experiments/results/2026-04-14_phase-a1_token-logging.md`
- DAD 패킷: `Document/dialogue/sessions/2026-04-14-phase-a1-token-logging/turn-{01..04}.yaml`
- 세션 state: `Document/dialogue/sessions/2026-04-14-phase-a1-token-logging/state.json`

## Open Follow-ups (A1 스코프 외)

- `pipeline/main.py` 로거 설정이 INFO 이상으로 필터될 가능성 — Phase A4 종단 테스트에서 파일 영속성 재검증.
- Claude CLI 응답 스키마 변화에 대한 silent drop — Phase C1(비용 모니터링) 에서 "usage 로그 부재" 경보로 보강.
- Codex 실행 환경의 Claude CLI 인증 401 — 저장소 밖 환경 이슈. 본 세션의 수렴 조건은 아님.

## 다음

Phase A2 (토큰 기준 청크 분할) 를 새 DAD 세션에서 시작한다. A1 의 토큰 로그가 A2 의 baseline 측정 도구 역할을 한다.
