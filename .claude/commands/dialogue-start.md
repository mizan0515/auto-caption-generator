---
description: Codex와의 Dual-Agent Dialogue v2 세션 시작 (대칭 턴)
argument-hint: "[작업 설명]"
---

# /dialogue-start

Codex와 Claude Code 간 대칭 턴 기반 Dialogue 세션을 시작한다.

## 인자

- `$ARGUMENTS` = 작업 설명 (한 줄). 비어 있으면 프로젝트 상태를 분석하여 자동 제안.

## 절차

1. `PROJECT-RULES.md`를 먼저 읽고, 그다음 `CLAUDE.md`와 `DIALOGUE-PROTOCOL.md`를 읽어 v2 프로토콜을 숙지한다.
2. 현재 프로젝트 상태를 분석한다:
   - `git log --oneline -10` (최근 작업 흐름)
   - `git status` (현재 변경 사항)
   - 최근 실패 테스트, CI 기록, 또는 로컬 검증 로그가 있으면 확인
   - 저장소 전용 research / inventory / architecture 문서가 있으면 확인
   - 런타임, 에디터, 또는 서비스 로그를 다루는 저장소면 관련 오류 로그를 확인
3. 작업 scope를 판단한다 (small / medium / large).
4. **Turn 1을 수행한다**:
   a. Sprint Contract 초안 작성 (medium/large일 때):
      - 구체적 체크포인트 목록 (검증 방법 포함)
      - `reference_prompts` 연결
   b. 계획 수립 + 부분 실행
   c. 자체 반복 루프: 체크포인트 기준 자체 검증, 만족할 때까지 반복
   d. Turn Packet을 `Document/dialogue/sessions/{session-id}/turn-01.yaml`로 저장
5. `Document/dialogue/state.json` 초기화/업데이트.
6. Codex용 프롬프트를 사용자에게 출력한다 (CLI 래퍼 없이 프롬프트 본문만).
   프롬프트에는 반드시 아래 6개 요소를 포함한다:
   - `Read PROJECT-RULES.md first. Then read AGENTS.md and DIALOGUE-PROTOCOL.md.`
   - `Session: Document/dialogue/state.json`
   - `Previous turn: Document/dialogue/sessions/{session-id}/turn-01.yaml`
   - 구체적 작업 지시 (`handoff.next_task + handoff.context`)
   - 10줄 안팎의 relay-friendly 요약
   - 아래 필수 꼬리말 블록
   프롬프트 끝에 반드시 아래 꼬리말을 포함한다:
   ```
   ---
    허점이나 개선점이 있으면 직접 수정하고 diff를 보고하라.
    수정할 것이 없으면 "변경 불필요, PASS"라고 명시하라.
    중요: 관대하게 평가하지 마라. "좋아 보인다" 금지. 구체적 근거와 예시를 들어라.
    ```

## 사용자 선택

세션 모드를 선택할 수 있다:
- **자율**: ESCALATE만 사용자에게. 나머지 자동.
- **감독**: 모든 수렴에 사용자 확인 필요.
- **하이브리드** (기본): large scope 또는 confidence low일 때만 확인.

## 호출 예시

```
/dialogue-start 카드 보상 화면 버그 수정
/dialogue-start 맵 시스템 코드 감사
/dialogue-start
```
