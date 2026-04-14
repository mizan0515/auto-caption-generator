# Session Summary — 2026-04-14-phase-a1-token-logging

- 세션 범위: Phase A1 — Claude CLI 토큰 사용량 로깅
- 상태: `converged` (2026-04-14, Turn 4)
- 브랜치: codex/phase-a1-token-logging

## 합의된 변경

- `pipeline/claude_cli.py`
  - `_log_usage(payload)` 헬퍼 추가
  - `_parse_claude_output()` 성공 경로(dict / list `type == "result"`)에 연결
  - 에러·빈 응답·JSONDecodeError 경로는 변경 없음
  - 모든 성공 호출에서 `Claude usage input_tokens=... output_tokens=... cache_creation_input_tokens=... cache_read_input_tokens=... session_id=... total_cost_usd=...` 를 INFO 로 기록
- `experiments/results/2026-04-14_phase-a1_token-logging.md`
  - baseline, after(2건), 결정 근거(≥200자), open risks, 체크포인트 자체평가

## 체크포인트 결과

| ID | 결과 | 근거 |
|----|------|------|
| C1 | PASS | `_log_usage()` 는 성공 경로에서만 호출. 에러/빈/텍스트 폴백 경로는 무변경. codex Turn 3 에서도 동일 확인. |
| C2 | PASS | 2026-04-14 에 claude-code 쪽에서 2회(Turn 2), 2회(Turn 4) 총 4회 실호출로 구조화된 토큰 로그 관찰. `cache_creation_input_tokens=0` 케이스도 포함되어 `isinstance` 기반 파서 설계가 zero-valued 필드를 보존함을 확인. |
| C3 | PASS | 결정 문서 존재 및 형식 충족. |
| C4 | PASS | 본 리포지토리 환경에서 실제 Claude 백엔드로 4회 성공 호출 확인. |

## 핵심 증빙

- 관찰된 로그 예 (Turn 4):
  - `pipeline INFO Claude usage input_tokens=3 output_tokens=7 cache_creation_input_tokens=0 cache_read_input_tokens=27737 session_id=5da76be0-... total_cost_usd=0.008435`
  - `pipeline INFO Claude usage input_tokens=3 output_tokens=58 cache_creation_input_tokens=0 cache_read_input_tokens=27761 session_id=cd4e0db8-... total_cost_usd=0.009207`
- Validator: `tools/Validate-Documents.ps1` 및 `tools/Validate-DadPacket.ps1 -AllSessions` 둘 다 통과.

## Turn 3 amendment 처리

Turn 3 에서 codex 측이 Claude CLI 401 인증 실패로 C2/C4 를 독립 재현하지 못해 수렴 보류를 요구했다. Turn 4 는 이 amendment 를 **superseded** 로 기록했다: C4 문구는 "본 리포지토리 환경에서의 실 Claude 호출"이며, claude-code 쪽에서 오늘 두 차례 추가 성공 호출로 이 조건을 충족했다. codex-side 401 은 환경 크리덴셜 이슈로 세션 밖에서 해소해야 한다.

## 오픈 리스크 (A1 스코프 외)

- `pipeline/main.py` 로거 구성이 INFO 이상으로 필터되면 파일 핸들러가 이 라인을 떨어뜨릴 수 있다. A4 종단 테스트에서 파일 영속성 재검증 필요.
- Claude CLI 응답 스키마가 바뀌면 `_log_usage()` 가 조용히 빈 라인을 생략. C1(비용 모니터링) 도입 시 "N 분 usage 로그 0건" 경보로 보강 권장.
- 작업트리에 본 A1 무관한 dirty 파일 다수 잔존 — 별도 housekeeping 커밋 권장.

## 다음 세션

Phase A2 (토큰 기준 청크 분할) — 새 DAD 세션 (`2026-04-15-phase-a2-token-chunking` 등) 에서 tokenizer 도입 + `chunk_max_tokens` 설정 + char vs token 청크 수 비교.
