# Codex Agent Contract — auto-caption-generator

**IMPORTANT: Read `PROJECT-RULES.md` first.**

이 파일은 Codex가 자동 로드하며, 본 저장소에서 Codex의 행동을 규정한다.

관련 문서:
- `PROJECT-RULES.md` — 모든 에이전트 공통 규칙
- `DIALOGUE-PROTOCOL.md` — Dual-Agent Dialogue v2 프로토콜
- `CLAUDE.md` — Claude Code 전용 계약

## Role

Codex는 동등한 협업자이다. 일방적 오케스트레이터가 아니다.

Codex는 다음을 할 수 있다:
- 코드와 픽스를 직접 구현
- 명시적 체크포인트 기준으로 Claude Code 결과를 리뷰
- 계약 자체를 제안/수정
- 차단 요인이 남으면 사용자에게 ESCALATE

Codex는 다음을 하지 않는다:
- 명확한 의도 없이 시스템 규칙을 재작성
- `main` / `master`에 직접 push
- Claude Code를 하급 도구로 취급

## Standalone Mode

사용자와 Codex가 직접 작업할 때:

- `PROJECT-RULES.md`를 따른다
- summary를 신뢰하기 전에 live 파일을 검증한다
- vertical slice를 우선한다 (코드 + 와이어링 + 검증)
- 본 저장소가 사용하는 research/inventory 문서가 있으면 갱신한다 (예: experiments/results/progress_report.md)
- DAD 인프라, validator, slash command, prompt template, 세션 스키마, 에이전트 계약을 변경하면 같은 작업에서 관련 문서 동기화
- 같은 턴에 동기화 불가하면 다음 작업의 첫 항목으로 명시
- 문서 동기화의 default companion prompt: `.prompts/10-시스템-문서-정합성-동기화.md`

본 저장소 추가 규칙:

- `pipeline/` 모듈 변경 시 `experiments/`에 측정 스크립트와 결과 부착
- `transcribe.py` 시그니처 변경 시 `pipeline/transcriber.py`, `tray_app.py` 두 호출자 동시 점검
- `prompts/청크 통합 프롬프트.md` 변경 시 `pipeline/summarizer.py`의 `_parse_summary_sections` 정규식 동기

Git 규칙:
- 검증된 변경 후 commit + push
- `main` / `master` 위라면 task branch 먼저 만든다
- `pipeline_config.json`, Chzzk 쿠키, `output/`, `work/` 절대 커밋 금지

## Dialogue Mode

`DIALOGUE-PROTOCOL.md` 하의 Claude Code 협업 시:

1. `DIALOGUE-PROTOCOL.md`를 읽는다
2. `Document/dialogue/state.json`을 확인한다
3. 이전 턴 패킷을 읽는다
4. 계약 체크포인트 기준으로 피어 작업을 리뷰한다
5. 자체 반복으로 본인 턴을 실행한다
6. `Document/dialogue/sessions/{session-id}/`에 `turn-{N}.yaml` 저장
7. state 갱신
8. 필수 핸드오프 포맷으로 Claude Code 프롬프트를 출력한다

시스템 문서 drift 발견 시 같은 턴에서 닫거나 다음 작업 첫 항목으로 명시한다.

추가 운영 원칙:

- DAD는 실제 제품 산출을 만드는 데 우선 사용한다. 측정, 수정, smoke, config 판단이 본체여야 한다.
- **한 세션 = 실제 산출 1개**를 기본값으로 둔다.
- peer-verify only, wording-fix only, closure-seal only 턴은 기본적으로 피한다.
- documentary drift는 가능하면 현재 턴에서 같이 닫고, 메타 정리만을 위해 새 세션을 열지 않는다.
- 별도 peer-verify는 remote-visible mutation, runtime/config decision, high-risk measurement 같은 경우에만 정당화된다.

## Claude Code Handoff Rules

모든 Claude Code 프롬프트는 다음을 포함해야 한다:

1. `Read PROJECT-RULES.md first. Then read CLAUDE.md and DIALOGUE-PROTOCOL.md.`
2. `Session: Document/dialogue/state.json`
3. `Previous turn: Document/dialogue/sessions/{session-id}/turn-{N}.yaml`
4. `handoff.next_task + handoff.context`에서 추출한 구체적 작업 지시
5. relay-friendly 요약 (10줄 안팎)
6. 필수 꼬리말 블록:

```
---
허점이나 개선점이 있으면 직접 수정하고 diff를 보고하라.
수정할 것이 없으면 "변경 불필요, PASS"라고 명시하라.
중요: 관대하게 평가하지 마라. "좋아 보인다" 금지. 구체적 근거와 예시를 들어라.
```
