# Dual-Agent Dialogue Protocol (DAD v2)

Codex와 Claude Code가 대칭 턴으로 협업하는 프로토콜.

## Core Principles

1. Symmetric turns: both agents plan, execute, and evaluate.
2. Sprint Contract: done state is expressed as concrete checkpoints.
3. Self-iteration: each agent verifies its own work before handoff.
4. Live files first: repository reality beats stale memory.
5. Schema discipline: packets and state must validate.
6. System-doc sync: if DAD infra, validators, commands, prompt templates, or agent contracts change, sync the related docs in the same task or make that the first next task.

## Turn Flow

- Turn 1: analyze state, draft contract, execute first slice, self-iterate, write packet, output peer prompt.
- Turn 2+: review the peer turn against checkpoints, execute your own slice, self-iterate, write packet, output peer prompt.

## Turn Packet Shape

```yaml
type: turn
from: [codex | claude-code]
turn: 1
session_id: "YYYY-MM-DD-task"

contract:
  status: "proposed | accepted | amended"
  checkpoints: []
  amendments: []

peer_review:
  project_analysis: "..."        # Turn 1 only (optional on Turn 2+)
  task_model_review:              # Turn 2+ only (optional on Turn 1)
    status: "aligned | amended | superseded"
    coverage_gaps: []
    scope_creep: []
    risk_followups: []
    amendments: []
  checkpoint_results: {}          # always required
  issues_found: []                # always required
  fixes_applied: []               # always required

my_work:
  task_model: {}                  # recommended for large scope; optional otherwise
  plan: ""
  changes:
    files_modified: []
    files_created: []
    summary: ""
  self_iterations: 0
  evidence:
    commands: []
    artifacts: []
  verification: ""
  open_risks: []
  confidence: "high | medium | low"

handoff:
  next_task: ""
  context: ""
  questions: []
  ready_for_peer_verification: true
  suggest_done: false
  done_reason: ""
```

Rules:

- `my_work` is mandatory.
- `suggest_done` and `done_reason` live only under `handoff`.
- If `suggest_done: true`, `done_reason` is required.
- Closed sessions require a summary artifact.

## Shared State

State file: `Document/dialogue/state.json`

Session directory: `Document/dialogue/sessions/{session-id}/`

Root `state.json` tracks the currently active session only. When a new session is created, the root state is overwritten. Previous session state is preserved in `sessions/{session-id}/state.json`.

운영 선호 규칙:

- 목표, 검증 표면, 작업 소유 범위가 크게 바뀌면 하나의 긴 umbrella session보다 짧은 session-scoped slice를 우선한다.
- 새 세션이 현재 세션을 대체하면 이전 세션을 그냥 방치하지 말고 `superseded` 또는 다른 종료 상태로 명시적으로 닫는다.

Expected contents per session directory:

- `turn-{N}.yaml`
- `state.json`
- `summary.md` for session-scoped summary
- `YYYY-MM-DD-{session-id}-summary.md` for named summary on closed sessions

### State Schema

`state.json` (both root and session-scoped) must contain:

| Field | Required | Values |
|-------|----------|--------|
| `protocol_version` | always | `"dad-v2"` |
| `session_id` | always | string |
| `session_status` | always | `active` \| `converged` \| `superseded` \| `abandoned` |
| `relay_mode` | always | `"user-bridged"` |
| `mode` | always | `autonomous` \| `hybrid` \| `supervised` |
| `scope` | always | `small` \| `medium` \| `large` |
| `current_turn` | always | integer (0 before first turn) |
| `max_turns` | always | integer |
| `last_agent` | after first turn | `codex` \| `claude-code` |
| `contract_status` | always | `proposed` \| `accepted` \| `amended` |
| `packets` | always | array of relative paths |
| `closed_reason` | when status != `active` | string |
| `superseded_by` | when status == `superseded` | session-id string |

### Context Overflow

When an agent's context window fills mid-session:

1. Save the current work as a partial turn packet (set `confidence: low` and note the overflow in `open_risks`).
2. Start a fresh context and use `.prompts/04-세션-복구-재개.md` to resume safely.
3. The recovery prompt will re-read state.json and the latest turn packet to restore working context.

## Prompt Generation Rules

Every peer prompt must include:

1. `Read PROJECT-RULES.md first. Then read {agent-contract}.md and DIALOGUE-PROTOCOL.md.`
2. `Session: Document/dialogue/state.json`
3. `Previous turn: Document/dialogue/sessions/{session-id}/turn-{N}.yaml`
4. concrete `handoff.next_task + handoff.context`
5. 10줄 안팎의 relay-friendly 요약
6. the mandatory tail block

Mandatory tail:

```
---
허점이나 개선점이 있으면 직접 수정하고 diff를 보고하라.
수정할 것이 없으면 "변경 불필요, PASS"라고 명시하라.
중요: 관대하게 평가하지 마라. "좋아 보인다" 금지. 구체적 근거와 예시를 들어라.
```

## Validation

Use:

- `tools/Validate-Documents.ps1 -Root . -IncludeRootGuides -IncludeAgentDocs -Fix`
- `tools/Validate-DadPacket.ps1 -Root . -AllSessions`

Minimum moments to run validation:

1. after saving a turn packet
2. before recording `suggest_done: true`
3. before resuming a recovered session

## Prompt References

Base references in this template:

- `.prompts/01-시스템-감사.md`
- `.prompts/02-세션-시작-컨트랙트-작성.md`
- `.prompts/03-턴-종료-핸드오프-정리.md`
- `.prompts/04-세션-복구-재개.md`
- `.prompts/05-의견차이-디베이트-정리.md`
- `.prompts/06-수렴-종료-PR-정리.md`
- `.prompts/07-기존-프로젝트-도입-마이그레이션.md`
- `.prompts/08-템플릿-검토-개선.md`
- `.prompts/09-비상-세션-복구.md`
- `.prompts/10-시스템-문서-정합성-동기화.md`
- `.prompts/11-DAD-운영-감사.md`
