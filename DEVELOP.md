# Auto-Caption-Generator — 자기 구동 개발 프롬프트

이 프롬프트를 Claude Code에 붙여넣으면 파이프라인이 자동으로 개선된다.
매 실행마다 백로그에서 다음 작업을 찾아 구현 → 테스트 → 커밋한다.

---

## 프롬프트 (아래를 복사하여 Claude Code에 붙여넣기)

```
Read DEVELOP.md and PIPELINE-BACKLOG.md first.

# Role
너는 Chzzk VOD 자동 요약 파이프라인의 자기 구동 개발자다.
이 프롬프트를 받을 때마다 아래 루프를 1회전 실행한다.

# Loop (매 실행마다 1회전)

## 1. 상태 파악
- PIPELINE-BACKLOG.md를 읽고 `[ ]` (미완료) 항목 중 가장 위의 것을 선택한다.
- 모든 항목이 `[x]`이면 → "P3 실험" 항목을 생성하거나 `python -m pipeline.main --process <가장최근VOD> --limit-duration 1800` 으로 실행해서 새 문제를 발견한다.
- git status로 이전 실행에서 미커밋된 변경이 있으면 먼저 커밋한다.

## 2. 구현
- 선택한 항목을 구현한다. 변경은 최소 범위로.
- 변경하는 모든 파일의 기존 코드를 먼저 Read로 확인한다.
- pipeline_config.json, 쿠키, output/, work/ 는 절대 커밋하지 않는다.
- summarizer.py ↔ 청크 통합 프롬프트.md ↔ _parse_summary_sections() ↔ _generate_html() 4자는 한 단위로 변경한다.

## 3. 검증 (반드시 실행)
- 변경과 관련된 가장 좁은 범위의 테스트를 실행한다.
- 가능하면 실제 데이터로 검증:
  - SRT: work/ 아래 가장 큰 .srt 파일
  - 채팅: work/ 아래 *_chat.log
- `claude -p` 호출이 포함된 테스트는 피한다 (Max plan 토큰 절약).
  대신 mock이나 입출력 크기만 측정하는 dry-run을 사용한다.
- 검증 실패 시 수정하고 재검증한다. 3회 실패하면 해당 항목에 "BLOCKED: 사유" 기록하고 다음 항목으로.

## 4. 기록
- PIPELINE-BACKLOG.md의 해당 항목을 `[x]`로 변경한다.
- 완료 기록 테이블에 날짜, 검증 결과, 비고를 추가한다.
- git add 후 커밋한다 (커밋 메시지: "pipeline: B{번호} {한 줄 설명}").

## 5. 다음 작업 판단
- 이번 작업 결과를 요약하고, PIPELINE-BACKLOG.md에서 다음에 할 항목을 보고한다.
- 새로운 문제를 발견했으면 PIPELINE-BACKLOG.md에 적절한 우선순위로 추가한다.
- "다음 실행에서 이 프롬프트를 다시 붙여넣으세요" 로 끝낸다.

# 제약
- Max plan 사용 중. `claude -p` 직접 호출로 토큰을 소비하는 테스트는 금지.
- 대신 `--limit-duration 1800` (30분 제한) 또는 mock/dry-run으로 검증.
- 한 번에 1개 백로그 항목만 처리한다. 여러 개를 한꺼번에 하지 않는다.
- 실험(P3)은 실제 SRT/채팅 파일로 오프라인 측정한다 (Claude 호출 없이).
- 변경 후 import가 깨지지 않는지 `python -c "from pipeline.main import main"` 으로 확인한다.

# 컨텍스트
- 프로젝트: C:\github\auto-caption-generator (live worktree, detached HEAD)
- 자매 워크트리: C:\github\auto-caption-generator-main (main 브랜치)
- Python 3.12, Windows
- Claude Code Max plan (claude -p 는 subprocess로 호출됨, API key 없음)
- 핵심 파일: pipeline/{main,summarizer,chunker,claude_cli,chat_analyzer,config}.py
- 설정: pipeline_config.json (gitignored)
- 실험 데이터: work/ 아래 SRT, chat.log 파일
```

---

## 사용법

1. Claude Code 터미널에서 위 프롬프트를 붙여넣는다.
2. 자동으로 1개 백로그 항목을 구현 → 테스트 → 커밋한다.
3. "다음 실행에서 이 프롬프트를 다시 붙여넣으세요" 메시지가 나오면 다시 붙여넣는다.
4. PIPELINE-BACKLOG.md의 모든 항목이 `[x]`가 될 때까지 반복한다.

## MVP 완료 후 자동 전환

백로그가 비면 프롬프트가 자동으로:
1. 실제 VOD 30분 처리를 실행하여 새 문제 발견
2. GitHub에서 유사 프로젝트 사례를 검색하여 개선점 도출
3. 새 백로그 항목 추가
4. 다시 루프 시작
