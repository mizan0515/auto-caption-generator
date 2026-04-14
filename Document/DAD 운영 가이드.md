# DAD 운영 가이드

## 목적

이 문서는 다른 프로젝트에서 DAD v2 템플릿을 처음 켤 때 필요한 최소 운영 순서를 설명한다.

## 운영 모델

- DAD v2는 **user-bridged** 워크플로우다. auto 모드는 질문과 수렴 마찰을 줄일 뿐, 사용자 relay 단계를 제거하지 않는다.
- `Document/dialogue/state.json`은 현재 세션의 source of truth이고, `Document/dialogue/sessions/{session-id}/`는 durable artifact bundle이다.
- 작업 의미가 바뀌면 하나의 긴 umbrella session보다 짧은 session-scoped slice를 여러 개 닫는 방식을 우선한다.
- 새 세션이 현재 세션을 대체하면 조용히 방치하지 말고 이전 세션을 명시적으로 close 또는 supersede한다.
- `.agents/skills/`는 이 저장소의 스킬 source of truth다. Codex Desktop의 실제 자동 발견 경로는 프로젝트 로컬이 아니라 사용자 홈 아래의 전역 Codex skills 디렉터리이므로, 변경 후에는 동기화가 필요하다.
- `.agents/skills/` 아래의 스킬 본문 파일은 Codex Desktop 호환성을 위해 UTF-8 without BOM으로 유지한다. 문서 validator가 일반 문서와 같은 BOM 규칙을 강제하면 안 된다.
- 현재 Codex Desktop에서는 커스텀 스킬의 frontmatter 필드(`name`, `description`)와 UI 메타데이터 문자열을 ASCII/English로 유지하는 편이 가장 안전하다. 한글 메타데이터는 인덱싱이나 노출 단계에서 누락될 수 있다.
- `.agents/skills/`의 Codex/OpenAI 스킬은 **명시 호출 전용**(`allow_implicit_invocation: false`)으로 설정되어 있으므로 이름으로 직접 호출한다.

## 시작 순서

1. `PROJECT-RULES.md`를 해당 프로젝트에 맞게 채운다.
2. 필요하면 `AGENTS.md`, `CLAUDE.md`의 git / verification 정책을 조정한다.
3. 기존 저장소에 도입하는 경우 `.prompts/07-기존-프로젝트-도입-마이그레이션.md`를 먼저 사용해 충돌 지점을 정리한다.
4. 크로스플랫폼 환경이면 `pwsh` 7.2+가 설치되어 있는지 확인한다 (`tools/*.sh` wrapper와 pre-commit hook은 `pwsh` 기준).
5. 문서 검증을 한 번 실행한다.
6. `powershell -File tools/Validate-CodexSkillMetadata.ps1 -Root .`로 스킬 메타데이터를 검증한다.
7. `powershell -File tools/Sync-CodexSkills.ps1 -Root .`로 전역 Codex skills 디렉터리에 동기화한다.
8. 첫 세션을 생성한다.
9. Turn 1 packet을 만들고 작업을 시작한다.

참고:
- 아래 예시는 `pwsh` 기준이다.
- Windows PowerShell 5.1만 있는 환경이면 `pwsh -File` 대신 `powershell -ExecutionPolicy Bypass -File`로 바꿔 실행한다.

## 첫 세션 생성

```powershell
pwsh -File tools/New-DadSession.ps1 `
  -SessionId "YYYY-MM-DD-task" `
  -TaskSummary "Describe the task" `
  -Scope medium `
  -Mode hybrid
```

## 첫 턴 생성

```powershell
pwsh -File tools/New-DadTurn.ps1 `
  -SessionId "YYYY-MM-DD-task" `
  -Turn 1 `
  -From codex
```

## 기본 검증

문서 변경 후:

```powershell
pwsh -File tools/Validate-Documents.ps1 -Root . -IncludeRootGuides -IncludeAgentDocs -Fix
```

저장소 루트 밖에서 validator를 호출하면 `-Root`에 저장소 절대 경로를 명시한다.

```powershell
pwsh -File tools/Validate-Documents.ps1 -Root "C:\path\to\target-repo" -IncludeRootGuides -IncludeAgentDocs
```

세션 생성 후:

```powershell
pwsh -File tools/Validate-DadPacket.ps1 -Root . -AllSessions
```

## 운영 원칙

- 루트 계약 문서, command, skill, prompt, validator는 한 시스템으로 본다.
- 이 중 하나가 바뀌면 관련 문서를 같이 맞춘다.
- 못 맞추면 다음 작업의 첫 항목으로 명시한다.
- 목표, 검증 표면, 작업 소유 범위가 바뀌면 하나의 세션을 억지로 늘리지 말고 새 세션을 연다.
- 종료되거나 supersede된 세션도 `summary.md`와 named closed-session summary를 남긴다.
- 수렴 직전에는 `.prompts/06-수렴-종료-PR-정리.md`를 기준으로 summary, state, validation, 브랜치 정리를 빠뜨리지 않는다.
- 일반 재개로 복구할 수 없으면 `.prompts/09-비상-세션-복구.md`를 사용한다.
- 시스템이 실제로 운용된 뒤 live artifact 기준 운영 감사를 하려면 `.prompts/11-DAD-운영-감사.md`를 사용한다.
