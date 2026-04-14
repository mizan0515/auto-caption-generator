---
name: acg-repeat-workflow-auto
description: "Run the next turn of an active auto-caption-generator DAD v2 session in auto mode. Use when an existing repository session should continue with minimal relay overhead while still escalating when needed. Invoke explicitly with `$acg-repeat-workflow-auto`."
---

# Repeat Workflow Auto (judgment-light 모드)

`$acg-repeat-workflow`의 **judgment-light 변형**. 모호한 상황에서도 사용자에게 묻지 않고 자동 판단한다.

## 호출 방식

- 이 스킬은 자동 제안이 아니라 **명시 호출 전용**이다.
- 사용 예시: `$acg-repeat-workflow-auto로 현재 DAD v2 세션을 자율 모드로 계속 진행해라.`
- 세션이 아직 없다면 먼저 `$acg-dialogue-start`를 호출한다.

주의: 현재 DAD v2는 **user-bridged 프로토콜**이다. 자동화되는 것은 판단과 수렴 규칙이지, 사용자 relay 단계가 아니다.

## $acg-repeat-workflow와의 차이 (4가지 override)

1. **사용자 확인 최소화** — ESCALATE 외에는 자동 판단
2. **작업 선택 자율화** — 분석 결과에 따라 가장 가치 있는 작업을 자동 선택
3. **PASS 자동 커밋** — 모든 체크포인트 통과 시 작업 브랜치에 자동 커밋 + push + PR 생성 (main 직접 push 금지)
4. **정체 시 자동 전환** — 2턴 연속 같은 체크포인트 FAIL 시 다른 접근으로 자동 전환

## 절차

1. [PROJECT-RULES.md](../../../PROJECT-RULES.md)를 먼저 읽고, 그다음 [AGENTS.md](../../../AGENTS.md)와 [DIALOGUE-PROTOCOL.md](../../../DIALOGUE-PROTOCOL.md)를 읽는다.
2. Document/dialogue/state.json에서 기존 세션 상태를 확인한다 (없으면 먼저 `$acg-dialogue-start`를 호출한다).
3. 프로젝트 현재 상태를 자동 분석 (git log, 테스트, 콘솔).
4. 자율 실행:
   - Contract 자동 생성 → 작업 실행 → 자체 반복 → 상대용 프롬프트 생성 → 사용자 relay → 다음 턴 수렴 판단
5. 프롬프트에는 반드시 아래 6개 요소를 포함한다:
   - `Read PROJECT-RULES.md first. Then read CLAUDE.md and DIALOGUE-PROTOCOL.md.`
   - Session: Document/dialogue/state.json
   - Previous turn: Document/dialogue/sessions/{session-id}/turn-{N}.yaml
   - 구체적 작업 지시 (`handoff.next_task + handoff.context`)
   - 10줄 안팎의 relay-friendly 요약
   - 아래 필수 꼬리말 블록
6. 프롬프트 끝에 반드시 아래 꼬리말을 포함한다:
   ```
   ---
   허점이나 개선점이 있으면 직접 수정하고 diff를 보고하라.
   수정할 것이 없으면 "변경 불필요, PASS"라고 명시하라.
   중요: 관대하게 평가하지 마라. "좋아 보인다" 금지. 구체적 근거와 예시를 들어라.
   ```
7. 종료 시 Document/dialogue/sessions/{session-id}/에 세션 요약 기록.

## 안전 가드

1. 하드 턴 제한: 초과 시 즉시 중단
2. 3턴 연속 같은 체크포인트 FAIL → 자동 중단 + 사용자 보고
3. 컴파일 에러 해결 불가 → 중단 + 사용자 보고
4. main 브랜치 직접 push 금지
5. 2턴 연속 품질 정체 → 다른 접근으로 자동 전환
