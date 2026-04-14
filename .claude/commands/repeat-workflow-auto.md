---
description: Dual-Agent Dialogue v2 대칭 턴 judgment-light 실행 (사용자 확인 최소, relay 유지)
argument-hint: "[턴 수, 기본 5]"
---

# /repeat-workflow-auto

`/repeat-workflow`의 **judgment-light 변형**. 모호한 상황에서도 사용자에게 묻지 않고
자동 판단한다. ESCALATE만 사용자에게 전달한다.

주의: 현재 DAD v2는 **user-bridged 프로토콜**이다. 이 커맨드도 상대 에이전트 호출 자체를 숨기지 못한다.
자동화되는 것은 판단과 수렴 규칙이지, 사용자 relay 단계가 아니다.

감독이 필요하면 `/repeat-workflow N`을 사용하라.

## 인자
- `$ARGUMENTS` = 반복 턴 수 (1~10). 비어 있으면 5.

## /repeat-workflow와의 차이 (4가지 override)

1. **사용자 확인 최소화** — ESCALATE 외에는 자동 판단
2. **작업 선택 자율화** — 분석 결과에 따라 가장 가치 있는 작업을 자동 선택
3. **PASS 자동 수렴** — 모든 체크포인트 통과 시 작업 브랜치에 자동 커밋 + push + PR 생성
4. **정체 시 자동 전환** — 2턴 연속 같은 체크포인트 FAIL 시 다른 접근으로 자동 전환

## 절차

1. `PROJECT-RULES.md`를 먼저 읽고, 그다음 `CLAUDE.md`와 `DIALOGUE-PROTOCOL.md`를 읽는다.
2. `Document/dialogue/state.json`에서 기존 세션 상태를 확인한다 (없으면 `/dialogue-start`로 새 세션을 시작).
3. 프로젝트 현재 상태를 자동 분석 (git log, 테스트, 콘솔)
4. `$ARGUMENTS`턴 (또는 5턴) 자율 실행:
   - Contract 자동 생성 → 작업 실행 → 자체 반복 → 상대용 프롬프트 생성(필수 꼬리말 포함) → 사용자 relay → 다음 턴 수렴 판단
   - Turn Packet은 `Document/dialogue/sessions/{session-id}/turn-{N}.yaml`에 저장
   - 상대용 프롬프트에는 반드시 아래 6개 요소 포함:
     - `Read PROJECT-RULES.md first. Then read AGENTS.md and DIALOGUE-PROTOCOL.md.`
     - `Session: Document/dialogue/state.json`
     - `Previous turn: Document/dialogue/sessions/{session-id}/turn-{N}.yaml`
     - 구체적 작업 지시 (`handoff.next_task + handoff.context`)
     - 10줄 안팎의 relay-friendly 요약
     - 아래 필수 꼬리말 블록
   - 상대용 프롬프트 끝에 반드시 아래 꼬리말 포함:
     ```
     ---
     허점이나 개선점이 있으면 직접 수정하고 diff를 보고하라.
     수정할 것이 없으면 "변경 불필요, PASS"라고 명시하라.
     중요: 관대하게 평가하지 마라. "좋아 보인다" 금지. 구체적 근거와 예시를 들어라.
     ```
5. 종료 시 `Document/dialogue/sessions/{session-id}/`에 세션 요약 기록

## 안전 가드

1. 하드 턴 제한: 초과 시 즉시 중단
2. 3턴 연속 같은 체크포인트 FAIL → 자동 중단 + 사용자 보고
3. 컴파일 에러 해결 불가 → 중단 + 사용자 보고
4. main 브랜치 직접 push 금지
5. 2턴 연속 품질 정체 → 다른 접근으로 자동 전환
