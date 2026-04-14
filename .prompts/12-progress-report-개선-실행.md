# 12. Progress Report 기반 개선 실행

## 목적

`experiments/results/progress_report.md`에서 정리한 한계와 문제점을 순차적으로 해소한다.
이 프롬프트는 한 세션(또는 한 턴)에서 **단일 Phase 단일 항목**만 다룬다.
여러 항목을 묶어서 처리하지 않는다 — 각 항목은 측정 근거가 독립적으로 필요하다.

## 필수 선행 읽기

1. `PROJECT-RULES.md` — source-of-truth 순서, guardrails, 검증 기대치
2. `experiments/results/progress_report.md` — 본 세션의 baseline 한계 목록
3. 선택 대상 항목이 언급한 live 파일 (예: `pipeline/summarizer.py`, `pipeline/claude_cli.py`, `pipeline/subtitle_analyzer.py`)
4. 관련 최신 실험 결과 (`experiments/results/summary.md` 등)

## 입력

- `TARGET_PHASE`: `A` | `B` | `C` — 어떤 Phase에서 작업할지
- `TARGET_ITEM`: Phase 내 항목 번호 (예: Phase A 의 `1` = "토큰 사용량 로깅")
- `MODE`: `plan-only` | `execute` | `measure-only`
  - `plan-only` = 실행 전 체크포인트 계약만 작성
  - `execute` = 코드 변경 + 검증까지 수행
  - `measure-only` = 기존 상태 측정만 (변경 없음)

입력이 비어 있으면 progress_report의 "우선순위 다음 단계" 섹션을 읽고
가장 상위 미완료 항목을 **자동 선택**한 뒤, 본 세션에서 다룰 단일 항목을 제안한다.
사용자 승인 전까지 `execute` 모드로 진입하지 않는다.

## 작업 범위 테이블 (progress_report.md 기준)

### Phase A — 신뢰성 확보

| 항목 | 목표 산출물 | 검증 기준 |
|---|---|---|
| A1. 토큰 사용량 로깅 | `pipeline/claude_cli.py`가 응답 `usage` 파싱 후 in/out tokens 로깅 | 30분 VOD 1회 호출 시 로그에 `input_tokens=`, `output_tokens=`, `cache_*` 출력 |
| A2. 토큰 기준 분할 | `tiktoken` 또는 Anthropic 토크나이저 도입, `chunk_max_tokens` 설정 추가 | 동일 SRT를 chars/tokens 두 기준으로 분할하여 청크 수 차이 비교표 |
| A3. 실험 재실행 | `experiments/chunk_size_experiment.py`를 새 프롬프트 + 토큰 측정 포함으로 갱신 | 30분/1시간/3시간 각 1샘플 결과가 `experiments/results/`에 MD로 남음 |
| A4. 풀 파이프라인 종단 테스트 | 신규 VOD 1개 자동 처리 → md/html/json 3파일 생성 | `output/`에 3파일 존재 + 사람이 HTML 열어 시각 검수 |

### Phase B — 품질 향상

| 항목 | 목표 산출물 | 검증 기준 |
|---|---|---|
| B1. 강조어 사전 확장 | `pipeline/subtitle_analyzer.py`의 `_EMPHASIS_WORDS`에 100+ 항목, 또는 TF-IDF 동적 추출 | baseline 대비 자막 피크 상위 15개 중 의미 있는 구간 비율 ↑ (수동 라벨링) |
| B2. 커뮤니티 매칭 검수 | `pipeline/community_matcher.py` 매칭 샘플 30개 수동 검수 | 허위 매칭(stopword, 일반어)이 10% 미만 |
| B3. SRT 전처리 통합 결정 | `srt-preprocessing.py`를 `pipeline/`에 통합 OR 명시적 제거 결정 문서화 | 결정 근거 ≥ 200자 decision 문서 (experiments/results 하위, 파일명: srt_preprocessing_decision) |

### Phase C — 운영 성숙도

| 항목 | 목표 산출물 | 검증 기준 |
|---|---|---|
| C1. 비용 모니터링 | VOD당 토큰·추정 비용 집계, 일일 리포트 | output/logs 하위 cost_summary jsonl 파일 누적 |
| C2. 재개 로직 강화 | 단계별 체크포인트 자동 감지 + resume | 중간 실패 재현 후 resume 시 완료 단계 skip 확인 |
| C3. 장르별 프로파일 | 스트리머/카테고리별 청크 / 강조어 설정 분기 | `pipeline_config.json`에 `profiles` 키 추가 + 분기 로직 |

## 절차

1. **상태 읽기**: live 파일 읽고 현재 상태를 진술한다. memory/summary 신뢰 금지.
2. **체크포인트 초안**: 선택한 `TARGET_ITEM`에 대해 구체적 체크포인트 3~5개. 각 체크포인트는 "어떤 파일/라인이 어떻게 변경되어야 PASS"인지 명시.
3. **측정 baseline**: 변경 전 수치를 먼저 측정해 기록한다. (이것 없이 개선 주장 금지)
4. **변경 구현**: `MODE=execute`일 때만. 최소 단위로 작업.
5. **측정 after**: 변경 후 동일 지표로 재측정. baseline과 나란히 기록.
6. **결과 기록**: `experiments/results/{YYYY-MM-DD}_{item-id}.md`에 before/after, 결정, 남은 위험 기록.
7. **문서 동기화**: 본 작업으로 `pipeline/config.py` 기본값, `prompts/청크 통합 프롬프트.md`, 파서 정규식, HTML 템플릿, PROJECT-RULES.md guardrail 중 하나라도 바뀌면 같은 턴에서 동기화. 불가하면 handoff.next_task에 first item으로 명시.

## 금지

- **측정 없는 개선 주장** — baseline 수치 없이 "개선됨" 금지
- **모듈 캐싱 함정** — 실험 재실행 시 이전 세션과 같은 Python 프로세스 재사용 금지 (서브프로세스 or importlib.reload)
- **scope creep** — 한 세션에서 Phase A1 + A2 동시 처리 금지 (각각 독립 측정 필요)
- **로그만 추가하고 "A1 완료" 선언** — 실제 VOD 1개 호출해서 로그 출력 확인까지 해야 완료
- **`_archive/` 코드 import** — PROJECT-RULES.md guardrail 위반
- **쿠키/민감 값 커밋** — `pipeline_config.json` git add 금지

## 성공 조건

본 세션이 close되려면 전부 충족:

- [ ] `TARGET_ITEM`의 모든 체크포인트 PASS
- [ ] before/after 측정값이 같은 파일에 기재
- [ ] `experiments/results/` 또는 해당 decision 문서에 결정 근거 ≥ 200자
- [ ] 관련 시스템 문서(PROJECT-RULES.md guardrail, README.md, CLAUDE.md) 동기화 완료 또는 next_task 명시
- [ ] `powershell -File tools/Validate-Documents.ps1 -Root . -IncludeRootGuides -IncludeAgentDocs` 통과
- [ ] 본 작업이 DAD 세션 내부라면 `tools/Validate-DadPacket.ps1 -Root . -AllSessions` 통과

## 출력 형식

체크포인트 결과는 아래 형식으로 출력:

```
TARGET: Phase A / A1 — 토큰 사용량 로깅
MODE: execute

BASELINE (변경 전):
  - pipeline/claude_cli.py:42 현재 usage 파싱 없음
  - 30분 VOD 실행 시 로그에 토큰 정보 0건

CHECKPOINTS:
  CP1 [PASS]: claude_cli.call_claude() 가 response.usage 파싱
    근거: pipeline/claude_cli.py:L58-L72 diff
  CP2 [PASS]: 로그에 input/output tokens 기록
    근거: output/logs/pipeline.log 마지막 30분 실행에 `input_tokens=` 3회 출현
  CP3 [FAIL]: cache_read_input_tokens 필드 누락
    이유: response JSON 구조에 cache_* 키가 응답 모델에 따라 다름, 조건부 접근 필요
    조치: L70에 dict.get("cache_read_input_tokens") 추가

AFTER (변경 후):
  - 실제 호출 1회의 usage: input=35421, output=4120, cache_read=2048

OPEN RISKS:
  - Anthropic SDK 버전 변경 시 스키마 변화 가능 — 로그에 raw JSON 덤프도 함께

DECISION DOC: experiments/results/2026-04-14_phase-a1_token-logging.md (작성 완료)

DOC SYNC: PROJECT-RULES.md § Verification Expectations 에 "모든 claude 호출은 토큰 로깅" 추가 (L84)
```

## 사용 예시

```
/execute .prompts/12-progress-report-개선-실행.md
  TARGET_PHASE=A TARGET_ITEM=1 MODE=plan-only
```

```
/execute .prompts/12-progress-report-개선-실행.md
  TARGET_PHASE=B TARGET_ITEM=2 MODE=execute
```

자동 선택 모드:
```
/execute .prompts/12-progress-report-개선-실행.md
# → progress_report.md 상단의 미완료 Phase A 항목을 제안
```

---

허점이나 개선점이 있으면 직접 수정하고 diff를 보고하라.
수정할 것이 없으면 "변경 불필요, PASS"라고 명시하라.
중요: 관대하게 평가하지 마라. "좋아 보인다" 금지. 구체적 근거와 예시를 들어라.
