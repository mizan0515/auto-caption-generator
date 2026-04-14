---
name: acg-repeat-workflow
description: "Run the next turn of an active auto-caption-generator DAD v2 session. Use when this repository already has an open dialogue session and Codex should continue the workflow. Invoke explicitly with `$acg-repeat-workflow`."
---

# Repeat Workflow (대칭 턴 반복)

진행 중인 DAD v2 세션에서 다음 턴을 수행한다.

## 호출 방식

- 이 스킬은 자동 제안이 아니라 **명시 호출 전용**이다.
- 사용 예시: `$acg-repeat-workflow로 현재 DAD v2 세션의 다음 턴을 진행해라.`
- 세션이 아직 없다면 먼저 `$acg-dialogue-start`를 호출한다.

## 절차

1. [PROJECT-RULES.md](../../../PROJECT-RULES.md)를 먼저 읽고, 그다음 [AGENTS.md](../../../AGENTS.md)와 [DIALOGUE-PROTOCOL.md](../../../DIALOGUE-PROTOCOL.md)를 읽는다.
2. Document/dialogue/state.json에서 기존 세션 상태를 확인한다 (없으면 `$acg-dialogue-start` 사용을 안내).
3. 이전 Turn Packet (Document/dialogue/sessions/{session-id}/turn-{N}.yaml)을 읽는다.
4. 현재 턴을 수행한다:
   a. **상대 작업 피드백**: Contract 체크포인트 기준 PASS/FAIL + evidence
   b. **자기 계획 + 실행**: 자체 반복 루프 수행
   c. **Turn Packet 저장**: Document/dialogue/sessions/{session-id}/turn-{N}.yaml
   d. **상대용 프롬프트 생성**: 사용자에게 프롬프트 본문 출력 (CLI 래퍼 불포함)
      - `Read PROJECT-RULES.md first. Then read CLAUDE.md and DIALOGUE-PROTOCOL.md.`
      - Session: Document/dialogue/state.json
      - Previous turn: Document/dialogue/sessions/{session-id}/turn-{N}.yaml
      - 구체적 작업 지시 (`handoff.next_task + handoff.context`)
      - 10줄 안팎의 relay-friendly 요약
      - 아래 필수 꼬리말 블록
   e. **수렴 판단**: 모든 체크포인트 PASS + 양쪽 done → 작업 브랜치에 커밋 + push + PR 생성 (main 직접 push 금지)

   프롬프트 끝에 반드시 아래 꼬리말을 포함한다:
   ```
   ---
허점이나 개선점이 있으면 직접 수정하고 diff를 보고하라.
수정할 것이 없으면 "변경 불필요, PASS"라고 명시하라.
중요: 관대하게 평가하지 마라. "좋아 보인다" 금지. 구체적 근거와 예시를 들어라.
```

5. 수렴 시 세션 요약을 Document/dialogue/sessions/{session-id}/에 기록한다.

## 안전 가드

1. 하드 턴 제한: scope별 최대 턴 초과 시 중단
2. 2턴 연속 품질 정체 → 사용자 ESCALATE
3. 3턴 연속 같은 체크포인트 FAIL → 자동 중단
4. 컴파일 에러 → 먼저 해결 후 진행
5. main 브랜치 직접 push 금지
