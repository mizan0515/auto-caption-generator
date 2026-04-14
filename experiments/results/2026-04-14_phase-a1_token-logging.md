# Phase A1 — 토큰 사용량 로깅 (before/after)

- 작업일: 2026-04-14
- 대상: `pipeline/claude_cli.py`
- 브랜치: `codex/phase-a1-token-logging`
- 세션: `2026-04-14-phase-a1-token-logging`
- 관련 체크포인트: state.json C1~C4 / progress_report.md Phase A/1

## 1. Baseline (변경 전)

- `pipeline/claude_cli.py:46-70` (변경 전 기준) `_parse_claude_output()` 는 Claude CLI JSON 응답에서
  `result` / `error` 필드만 읽고 `usage` 블록은 전혀 접근하지 않는다.
- `call_claude()` / `call_claude_with_context()` (변경 전 기준 L85-129) 의 debug 로그는 프롬프트 길이만 남기며
  토큰 수치는 어디에도 남기지 않는다.
- 실제 호출 1회(`echo "say hi in 3 words" | claude -p --output-format json --max-turns 1`)로 확인한 응답 스키마:

```
{"type":"result", "result":"...", "usage":{
    "input_tokens":2,
    "cache_creation_input_tokens":7069,
    "cache_read_input_tokens":20668,
    "output_tokens":8,
    ...
}, "total_cost_usd":..., "session_id":"..."}
```

- 즉 필요한 4개 토큰 필드(`input_tokens`, `output_tokens`, `cache_creation_input_tokens`,
  `cache_read_input_tokens`)는 이미 CLI 응답에 존재하지만 파이프라인이 버리고 있다.
- 이 상태에서는 progress_report.md "Phase A/1. 토큰 사용량 로깅" 검증 기준
  ("30분 VOD 1회 호출 시 로그에 `input_tokens=`, `output_tokens=`, `cache_*` 출력") 을 충족할 수 없다.

## 2. 변경 요약

1. `pipeline/claude_cli.py` 에 private helper `_log_usage(payload: dict)` 를 추가.
   - `payload["usage"]` 가 dict 일 때만 동작.
   - `input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens` 를 이 순서로
     `int()` 변환하여 `key=value` 토큰으로 모은다.
   - 하나도 못 얻으면 로그를 남기지 않는다 (기존 result/error 파싱 경로 보호).
   - `session_id`, `total_cost_usd` 가 있으면 동일 라인에 꼬리로 붙인다.
   - 로그 레벨은 `INFO` (pipeline 운영 로그에 기본 수집되는 레벨).
2. `_parse_claude_output()` 의 성공 경로에서 `_log_usage(...)` 를 호출.
   - dict 응답 (`"result" in data`) 과 list 응답(`type == "result"` 항목) 양쪽 모두.
   - 에러 경로/빈 응답 경로에서는 호출하지 않음 → 기존 예외 동작 그대로 유지.
3. `call_claude()` / `call_claude_with_context()` 본체는 건드리지 않음
   — 두 경로 모두 `_parse_claude_output()` 을 거치므로 단일 지점에서 커버됨.

## 3. After (변경 후 측정)

### 3.1 `call_claude()` 실경로

실행 명령:

```
python -c "
import logging, sys
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(name)s %(levelname)s %(message)s', stream=sys.stderr)
from pipeline.claude_cli import call_claude
out = call_claude('Reply with exactly: OK-A1', timeout=180)
print('RESULT:', repr(out))
"
```

출력 (stderr 로그 발췌):

```
2026-04-14 18:55:45,923 pipeline INFO Claude usage input_tokens=3 output_tokens=7 cache_creation_input_tokens=7069 cache_read_input_tokens=20668 session_id=95a679be-bc9a-412d-86a1-e75885334f05 total_cost_usd=0.032823
RESULT: 'OK-A1'
```

- 4개 토큰 필드 전부 로그에 기록됨.
- result 문자열(`'OK-A1'`) 도 기대한 대로 반환됨 → 기존 result 파싱이 깨지지 않음.

### 3.2 `call_claude_with_context()` 실경로

실행 명령:

```
python -c "
import logging, sys
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s', stream=sys.stderr)
from pipeline.claude_cli import call_claude_with_context
out = call_claude_with_context('Summarize the context in 3 words.', 'Two streamers played co-op rhythm game and laughed for 30 minutes.', timeout=180)
print('RESULT:', repr(out))
"
```

출력:

```
2026-04-14 18:55:55,885 pipeline INFO Claude usage input_tokens=3 output_tokens=12 cache_creation_input_tokens=7093 cache_read_input_tokens=20668 session_id=65313e04-d945-49cc-8706-a9e63ce94c5c total_cost_usd=0.032988
RESULT: '**Rhythm co-op laughter.**'
```

- 컨텍스트 경로도 동일한 로그 포맷으로 4개 필드 모두 기록.
- 반환 문자열은 정상 result (`'**Rhythm co-op laughter.**'`).

### 3.3 회귀 방어

- `_log_usage()` 는 `result["type"] == "error"` 경로보다 **뒤에** 호출되지 않는다 (에러 경로는 예외를 먼저 raise) → 에러 로깅 경로 영향 없음.
- `usage` 가 없거나 dict 가 아닐 경우 조기 return → 텍스트 모드(JSONDecodeError) 호환 유지.
- 토큰 필드가 하나도 없으면 로그 라인 자체를 남기지 않음 → 노이즈 방지.

## 4. 결정 근거 (≥200자)

Phase A1 은 progress_report.md 가 Phase A 신뢰성 확보의 선두 과제로 지정한 항목으로, 토큰 수치 없이는 A2(토큰 기준 분할), A3(실험 재실행), C1(비용 모니터링) 어느 것도 측정 기준을 세울 수 없다. Claude CLI 가 `--output-format json` 모드에서 이미 `usage` 를 반환하므로 새 의존성 도입 없이 기존 파이프라인 파서 한 곳에서 싱글 헬퍼로 처리하는 것이 최소 침습이다. `call_claude()` 와 `call_claude_with_context()` 모두 `_parse_claude_output()` 을 공유하므로 호출부 시그니처와 재시도 데코레이터를 건드릴 이유가 없다. 로그 레벨을 `INFO` 로 고른 이유는 pipeline 운영 로그(`output/logs/`) 가 기본 INFO 수집이며, 토큰 사용량은 비용 감사와 회귀 추적 양쪽에 필요하므로 DEBUG 로 숨기면 A2/C1 에서 다시 레벨을 끌어올려야 하기 때문이다. 에러 응답·빈 응답·텍스트 응답 경로에서는 의도적으로 호출하지 않아 기존 예외 동작과 stdout 폴백을 보존했고, 토큰 필드가 부분적으로 비어 있어도(예: CLI 업그레이드 후 스키마 변경) 로그 라인을 생략함으로써 관측 가능성과 안정성의 기본 경계를 동시에 지켰다.

## 5. Open risks / Follow-ups

- Claude CLI 응답 스키마가 향후 바뀌면 `_log_usage()` 가 조용히 라인을 남기지 않게 되며, 알림이 없다 → C1(비용 모니터링) 도입 시 "N 분 동안 usage 로그 0건" 경보를 같이 넣는 것이 바람직.
- 본 세션은 30분 VOD 종단 실행으로 검증하지 않았다. `call_claude()` / `call_claude_with_context()` 두 엔트리포인트를 **실제 Claude 백엔드**로 직접 호출해 토큰 로그가 출력되는 것을 확인한 수준이다. 30분 VOD 전체 파이프라인 smoke 는 Phase A4 의 책임 범위이므로 A1 PASS 기준으로는 충분하지만, 추후 A4 실행 시 `Claude usage` 라인 총량이 청크 수와 일치하는지 회귀 점검을 기대.
- `output/logs/` 파일 로거가 켜진 환경에서만 파일에 영속화되며, 본 검증은 stderr 스트림에서만 확인했다. 운영 로깅 경로는 `pipeline/main.py` 의 로깅 설정에 의존하므로 해당 설정이 변경되면 동일 라인이 파일로도 남는지 재검증이 필요하다.

## 6. Checkpoint 자체평가

- C1 (usage 파싱, result/error 무회귀): PASS — `_parse_claude_output()` 성공 경로에만 `_log_usage()` 삽입, 에러/빈/텍스트 경로 unchanged.
- C2 (success log 에 토큰 노출): PASS — §3.1, §3.2 의 stderr 출력에 4개 토큰 필드 전부 기록.
- C3 (before/after decision doc): PASS — 본 문서, 결정 근거 ≥ 200자 포함.
- C4 (실 Claude 호출 1회 확인): PASS — §3.1 / §3.2 두 건 모두 실제 Claude 백엔드 응답.
