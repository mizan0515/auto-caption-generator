# Claude Code Contract — auto-caption-generator

**IMPORTANT: Read `PROJECT-RULES.md` first.**

이 파일은 Claude Code가 자동 로드하며, 본 저장소에서 Claude Code의 행동을 규정한다.

관련 문서:
- `PROJECT-RULES.md` — 모든 에이전트 공통 규칙
- `DIALOGUE-PROTOCOL.md` — Dual-Agent Dialogue v2 프로토콜
- `AGENTS.md` — Codex 전용 계약

별도 메모리 레이어:
- 사용자 auto-memory (Claude Code 홈 경로의 MEMORY.md) 는 본 저장소의 source-of-truth가 **아니다**. 참고용.
- 본 저장소의 권위는 `PROJECT-RULES.md` ▶ live 코드 ▶ `pipeline_config.json` ▶ `prompts/청크 통합 프롬프트.md` ▶ `README.md` 순.

## Repository Guardrails

- `PROJECT-RULES.md`를 따른다
- 메모리보다 live 저장소 상태를 우선
- 본 저장소가 사용하는 research/inventory 문서를 갱신한다 (예: experiments/results/progress_report.md)
- DAD 인프라, validator, slash command, prompt template, 세션 스키마, 에이전트 계약 변경 시 같은 작업에서 문서 동기화
- 같은 턴 동기화 불가하면 다음 작업 첫 항목으로 명시
- 문서 동기화 default companion prompt: `.prompts/10-시스템-문서-정합성-동기화.md`
- `main` / `master`에 직접 push 금지
- `pipeline_config.json`, Chzzk 쿠키, `output/`, `work/` 절대 커밋 금지

본 저장소 추가 규칙:

- `pipeline/summarizer.py` ↔ `prompts/청크 통합 프롬프트.md` ↔ `_parse_summary_sections()` ↔ `_generate_html()` 4자는 한 단위로 변경
- `transcribe.py` 변경 시 `pipeline/transcriber.py`, `tray_app.py` 두 호출자 동시 점검
- 파라미터 튜닝(청크 크기, 강조어 사전, 임계값 등)은 `experiments/`에 측정 스크립트 + 결과 기록 후 적용
- Python 모듈 캐싱 주의: 실험 재실행 시 importlib.reload 또는 신규 프로세스 사용

## Standalone Stance

직접 사용 시:

- 실파일을 먼저 검증
- 다중 시스템 변경 시 계획을 먼저 명시
- 변경 후 가장 좁은 유용 검증을 실행
- 변경이 self-contained하고 검증되면 commit + push
- 무관한 dirty 파일이 staging을 막으면 명시적으로 보고

## Dialogue Mode

`DIALOGUE-PROTOCOL.md` 하의 Codex 협업 시:

1. 현재 저장소 상태 분석
2. Turn 1이면 계약 초안 + 첫 실행 슬라이스
3. Turn 2+이면 체크포인트 기준 피어 턴 리뷰 후 본인 슬라이스 실행
4. 핸드오프 전 자체 반복
5. `Document/dialogue/sessions/{session-id}/turn-{N}.yaml`에 턴 패킷 저장
6. 필수 핸드오프 포맷으로 Codex 프롬프트 출력
7. 시스템 문서 drift 잔존 시 같은 턴에 닫거나 다음 작업 첫 항목으로 명시

## Codex Handoff Rules

모든 Codex 프롬프트는 다음을 포함해야 한다:

1. `Read PROJECT-RULES.md first. Then read AGENTS.md and DIALOGUE-PROTOCOL.md.`
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
