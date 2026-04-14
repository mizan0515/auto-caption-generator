# Dialogue 세션 레이아웃

`Document/dialogue/`는 live DAD v2 세션 산출물을 보관한다.

## 예상 구조

- `state.json`
- `sessions/{session-id}/state.json`
- `sessions/{session-id}/turn-{N}.yaml`
- `sessions/{session-id}/summary.md`
- 종료된 세션의 경우 `sessions/{session-id}/YYYY-MM-DD-{session-id}-summary.md`

## 규칙

- 템플릿에 가짜 세션을 미리 심어두지 않는다.
- 첫 세션은 `tools/New-DadSession.ps1`로 생성한다.
- 각 신규 턴 파일은 `tools/New-DadTurn.ps1`로 생성한다.
- 짧은 session-scoped slice를 기본으로 삼고, 목표나 검증 표면이 크게 바뀌면 하나의 세션을 억지로 늘리지 말고 새 세션을 연다.
- 새 세션이 현재 세션을 대체하면 이전 세션을 명시적으로 close 또는 supersede하고 summary 산출물을 유지한다.
- `tools/Validate-DadPacket.ps1 -Root . -AllSessions`는 live 세션이 없는 동안 skip 메시지를 출력하며, 첫 세션 생성 이후부터 필수가 된다.
- 패킷 수정 이후와 세션을 done으로 표시하기 전에 `tools/Validate-DadPacket.ps1 -Root . -AllSessions`를 실행한다.
