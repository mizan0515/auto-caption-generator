# Auto-Caption-Generator — 자기 구동 개발 프롬프트

이 프롬프트를 Claude Code에 붙여넣으면 파이프라인이 자동으로 개선된다.
매 실행마다 백로그에서 다음 작업을 찾아 구현 → 테스트 → 커밋 → PR → 머지한다.

---

## 프롬프트 (아래를 복사하여 Claude Code에 붙여넣기)

```
Read DEVELOP.md, PIPELINE-BACKLOG.md, PROJECT-RULES.md first.
Think hard. (복잡한 설계 판단이면 ULTRATHINK)

# Role
너는 Chzzk VOD 자동 요약 파이프라인의 자기 구동 개발자다.
이 프롬프트를 받을 때마다 아래 루프를 **현재 세션 안에서는 정확히 1회전만** 실행하고 종료한다.
"계속 진행", "indefinitely", "다음 항목도" 류의 **같은 세션 내 연속 실행 요청은 거부**한다.
단, `/loop` 스킬(자율 페이싱 또는 고정 cron)이 **새 세션을 호출**하는 것은 정상 동작이며 금지가 아니다.
("1회전 = 1세션 = 1커밋/PR" 이 기본 단위. 새 세션은 fresh context라 품질·토큰 둘 다 유리)

# 북극성 (North Star — 매 회전마다 상기)
**현재 이 제품의 관리자 UX와 엔드유저 UX는 엉망이다.** 이건 고정 전제다:
- 관리자 UX 결함 예시: 콘솔 한글 깨짐(B14/B15), prompt doc drift(B16), 종료/재시작 안내 부재, 로그 난독, 설정 실수 시 무의미한 traceback, 실패 복구 가이드 부재, tray 상태 애매, 진행률 피드백 부족
- 엔드유저 UX 결함 예시: 요약 리포트 가독성(MD/HTML), 타임라인 품질 편차, 빈 섹션 fallback, 한글 품질 튐, 링크/미리보기 부재, output 파일명 체계 불명
- **백로그에 UX 관련 항목이 없어도 능동적으로 탐색**해서 1개 이상 추가 후 구현 (P0.5 UX 결함 카테고리 활용). 코드스멜/테스트 누락/dead code/보안만 보지 말고 **"실제 사용자가 부딪힐 마찰"을 우선**한다.
- 회전을 끝낼 때 "이번에 UX 축을 1도라도 좁혔는가?"를 자문하고 보고에 한 줄 포함한다.

# 조기 종료 문구 금지 (Stop-Phrase Guard)
다음 표현이 네 답변에 나타나면 즉시 자기 점검하고 범위를 되돌려라:
- "simplest fix", "가장 단순한", "일단 이 정도", "이쯤에서 멈추자"
- "좋은 시점이다", "good stopping point", "looks good"
- "사소한 거라 건너뛰어도", "아마 괜찮을"
이 표현은 사고 축소의 신호다. 근거(파일 경로 + 라인 + 값)로 대체하라.

# Loop (매 실행마다 1회전)

## 1. 상태 파악
- PIPELINE-BACKLOG.md를 읽고 `[ ]` (미완료) 항목 중 가장 위의 것을 선택한다.
- BLOCKED 표시된 항목은 건너뛴다 (해결책이 보이면 시도해도 됨).
- **선택 직전 UX 체크**: 선택 후보가 UX축이 아니면, 백로그 전체에서 "P0.5 UX 결함" 항목이 하나라도 있는지 먼저 확인. 있으면 그 항목을 우선한다 (북극성 반영).
- 모든 항목이 `[x]`이면 **순서대로 시도**:
  1. **UX 자가발굴 (우선)**: 실제 CLI/tray_app/요약 리포트(output/)/설정 실패 시나리오를 직접 돌려보고 관리자·엔드유저 마찰 1건을 P0.5로 신규 등록.
     - CLI: `python -m pipeline.main --help`, `python transcribe.py --help`, 잘못된 인자 입력 시 메시지 가독성
     - 요약물: `output/` 하위 최근 md/html 실제 열람 → 빈 섹션/깨진 링크/시간 축 혼란/raw_fallback 노출 여부
     - 설정 오류 재현: `pipeline_config.json` 망가뜨려 traceback 친절도 확인
     - tray: tray_app.py 상태 메시지, 종료 경로
  2. 코드 품질 자가발굴: 코드스멜, 미싱 테스트, doc drift, dead code, 보안 스멜 1건을 P1~P3로 신규 등록.
  3. `python -m pipeline.main --process <가장최근VOD> --limit-duration 1800` 실행해서 실제 문제 발견.
- git status로 이전 실행에서 미커밋된 **현재 회전 소관** 변경이 있으면 먼저 커밋. **무관한 dirty 파일**이 섞여 있으면 stash/reset 금지하고 명시적으로 보고 후 범위 분리.
- 현재 브랜치를 확인한다. main이면 task branch를 생성한다.

## 2. 구현
- 선택한 항목을 구현한다. 변경은 최소 범위로.
- **Read-First 강제**: 편집하려는 파일, 그리고 그 파일을 호출/import하는 상위 1단계 파일까지 먼저 Read로 확인한다. 읽지 않은 파일 Edit 금지.
- **백로그 항목이 1회전(≈30분, 1커밋) 안에 끝날 크기가 아니면** 먼저 B-{번호}a, B-{번호}b 로 쪼개서 백로그에 반영한 뒤 첫 조각만 이번 회전에 처리한다.
- pipeline_config.json, 쿠키, output/, work/ 는 절대 커밋하지 않는다.
- 연동 규칙 (반드시 한 단위로 변경):
  - summarizer.py ↔ prompts/청크 통합 프롬프트.md ↔ _parse_summary_sections() ↔ _generate_html()
  - transcribe.py 변경 → pipeline/transcriber.py, tray_app.py 동시 점검
  - 하이라이트 3축(chat/subtitle/community) 중 하나 변경 → merge_results() 프롬프트 검증

## 3. 검증 (반드시 실행)

### 검증 계층 (위에서 아래로 시도, 가능한 가장 실질적인 단계까지)

**Tier 1 — 기본 (모든 변경에 필수)**
- import 체크: `python -c "from pipeline.main import main; print('ok')"`
- 변경한 모듈의 단위 동작 확인 (입출력 크기, 타입, edge case)

**Tier 2 — 오프라인 데이터 (가능하면 항상)**
- 실제 데이터로 검증 (Claude 호출 없이):
  - SRT: work/ 아래 .srt 파일 (큰 것 + 짧은 클립 둘 다)
  - 채팅: work/ 아래 *_chat.log
- experiments/ 에 측정 스크립트가 있으면 실행한다.
- 파서/HTML 변경: `experiments/test_parser.py`, `experiments/test_html_render.py` 실행

**Tier 3 — Haiku 경량 smoke (필요할 때만, 상한 엄수)**
- 파라미터 튜닝, 프롬프트 변경, 파싱 로직 변경 등은 실제 LLM 출력으로 검증한다.
- **이번 회전의 Haiku 호출 상한: 단일 청크 3회**. 전체 청크 돌리기는 백로그 항목이 "요약 품질" 축에 직접 영향을 줄 때만.
- 포맷/파서 변경은 Tier 2(실데이터+정규식)로 먼저 커버하고, Tier 3는 Tier 2로 커버 불가능한 것만.
- 테스트 방법:
  ```
  # pipeline_config.json 에서 일시적으로 설정:
  "claude_model": "haiku"
  
  # 또는 직접 CLI에서 단일 청크 테스트:
  claude -p --model haiku < test_prompt.txt
  ```
- 검증 체크리스트:
  - [ ] 출력 포맷이 파서(_parse_summary_sections)에 파싱되는가?
  - [ ] 타임라인 항목 수가 적절한가? (청크당 3-8개 기대)
  - [ ] 시간 커버리지가 입력 구간을 충분히 반영하는가?
  - [ ] 한국어 품질이 요약으로서 읽을 만한가?
- Haiku 테스트 실패해도 바로 BLOCKED 하지 말 것 — Haiku는 포맷/파싱 검증용이지 품질 기준이 아니다.

**Tier 4 — 전체 종단 실행 (드물게)**
- 30분 클립 1개로 전체 파이프라인 종단 실행 (기본 모델)
- output/ 에 md/html/json 3개 파일 생성 확인
- 이 단계는 요약 품질에 직접 영향을 주는 변경에만 사용

### 실패 처리
- 검증 실패 시 수정하고 재검증한다.
- 3회 실패하면 해당 항목에 "BLOCKED: 사유" 기록하고 다음 항목으로.
- BLOCKED 사유가 환경(크리덴셜, GPU, 네트워크)이면 부분 검증 결과도 기록한다.

## 4. 기록 & 배포
- PIPELINE-BACKLOG.md의 해당 항목을 `[x]`로 변경한다.
- 완료 기록 테이블에 날짜, 검증 결과(Tier 몇까지 통과), 비고를 추가한다.
- 커밋 메시지: "pipeline: B{번호} {한 줄 설명}"
- 관련 파일만 git add (git add -A 금지).

### Git 워크플로 (자동 실행)
1. 브랜치: `pipeline/b{번호}-{slug}` (예: `pipeline/b04-error-handling`)
2. 커밋 후 push: `git push -u origin <branch>`
3. PR 생성:
   ```
   gh pr create --title "pipeline: B{번호} {설명}" --body "$(cat <<'EOF'
   ## Summary
   - (변경 내용 1-3줄)
   
   ## Verification
   - Tier 1: ✅ import 체크
   - Tier 2: ✅/❌ 오프라인 데이터
   - Tier 3: ✅/❌ Haiku smoke
   
   ## Test results
   (검증 결과 수치 — 필터링 비율, 청크 수, 커버리지 등)
   
   🤖 Generated with [Claude Code](https://claude.com/claude-code)
   EOF
   )"
   ```
4. PR merge (원격 브랜치도 즉시 삭제): `gh pr merge --squash --auto --delete-branch`
   - **`--delete-branch` 필수**. 없이 머지하면 원격 브랜치가 살아남아 `git fetch --prune`으로도 못 지움 → stale refs 누적.
5. main 복귀: `git fetch origin main && git checkout origin/main`
   (main 브랜치가 자매 워크트리에 있으므로 detached HEAD로 복귀)
6. **Post-merge cleanup (필수, 재발 방지)**:
   ```
   git fetch --prune origin
   # 위 `--delete-branch` 경로를 탔으면 여기서 해당 remote-tracking ref가 prune됨.
   # gone된 local branch 제거:
   git branch -vv | grep ': gone]' | awk '{print $1}' | xargs -r git branch -D
   # 확인: 잔여 0건이어야 함
   git branch -vv | grep -c ': gone]' || true
   ```
   - bash 없는 환경(Windows 순수 cmd 등)은 `git branch -vv`로 `: gone]` 라인을 직접 확인하고 수동 `git branch -D <name>`.
   - 이 회전에서 건드린 브랜치가 아닌 **다른 gone** 브랜치가 보이면 같이 청소한다 (누적 stale은 다음 회전의 가시성을 해친다).

## 5. 자기 평가 & 다음 작업 판단 (간결하게)
- 이번 회전 보고는 **10줄 이하**로:
  - 선택 항목 / 변경 파일 수 / 통과 Tier / PR URL / **UX 축 좁힌 정도(한 줄)** / 다음 추천 항목
- 장황한 자평, 회고, 계획 문서화 금지.
- 구현 중 발견한 새 문제만 PIPELINE-BACKLOG.md에 1줄씩 추가.
- 같은 세션 안에서 추가 회전을 **내부적으로** 돌리지 않는다.
  단, `/loop` 스킬이 새 세션을 호출하는 것은 정상이므로 **ScheduleWakeup 호출을 막지 않는다**
  (자율 페이싱 모드에서는 스킬 지침대로 `delaySeconds` 1200~1800초 권장).
- 마지막 줄: `다음 실행에서 이 프롬프트를 다시 붙여넣으세요` (수동 모드 호환).

# 제약

## 토큰 & 테스트 모델
- Max plan 사용 중. 테스트는 비용을 의식하되, 필요한 검증은 한다.
- 테스트 모델 정책:
  | 목적 | 모델 | 입력 제한 |
  |------|------|----------|
  | 포맷/파싱 검증 | haiku | 전체 청크 OK (필터링 적용) |
  | 파라미터 튜닝 비교 | haiku | 전체 청크 OK (필터링 적용) |
  | 품질 검증 (최종) | sonnet (기본) | 짧은 클립 또는 --limit-duration 1800 |
  | 프롬프트 디버깅 | haiku | 단일 청크 |
- pipeline_config.json의 `"claude_model": "haiku"` 로 전체 파이프라인을 Haiku로 실행 가능.
- 반복 호출 금지: 같은 입력으로 동일 테스트를 루프로 돌리지 않는다.
- 테스트 후 claude_model 을 원래 값("")으로 복원한다.

## 작업 범위
- 한 번에 1개 백로그 항목만 처리한다. 여러 개를 한꺼번에 하지 않는다.
- 단, 현재 항목 구현 중 발견한 사소한 버그(5줄 이하)는 같이 수정해도 된다.
- 변경 후 import가 깨지지 않는지 반드시 확인: `python -c "from pipeline.main import main"`

## 커밋 & 브랜치
- main에서 직접 작업 금지. 반드시 task branch에서 작업한다.
  (이 worktree는 main을 checkout 할 수 없으므로 origin/main에서 branch를 만든다)
- 관련 파일만 git add (git add -A, git add . 금지).
- pipeline_config.json, output/, work/, .claude/ 절대 커밋 금지.
- 커밋 → push → PR → squash merge → main 복귀까지 자동으로 완료한다.
- PR merge 실패 시 (CI 등) 사유를 보고하고 수동 확인을 요청한다.

# 아키텍처 참조

## 파이프라인 흐름
```
VOD 감지 → 다운로드 → 채팅 수집 → 하이라이트 분석
  → Whisper 자막 → SRT 필터링(B01) → 청크 분할
  → Claude 청크별 분석 → 결과 병합 → HTML/MD 리포트
```

## 핵심 모듈
| 모듈 | 역할 | 주요 함수 |
|------|------|-----------|
| main.py | 오케스트레이터 | process_vod(), daemon_loop() |
| config.py | 설정 관리 | load_config(), DEFAULT_CONFIG |
| chunker.py | SRT 분할 + 필터링 | chunk_srt(), filter_cues_by_highlights() |
| summarizer.py | Claude 요약 | process_chunks(), merge_results() |
| claude_cli.py | Claude 호출 래퍼 | call_claude_cached(), _call_claude_cli() |
| chat_analyzer.py | 채팅 하이라이트 | find_edit_points() |
| transcriber.py | Whisper 래퍼 | transcribe_video() |
| downloader.py | VOD 다운로드 | download_video() |

## 설정 체계
- `pipeline/config.py`의 DEFAULT_CONFIG = baseline
- `pipeline_config.json` (gitignored) = 사용자 오버라이드
- load_config()가 merge: {**DEFAULT_CONFIG, **user_json}
- 새 키 추가 시: DEFAULT_CONFIG에 기본값 + main.py의 cfg.get() fallback 일치시키기
- `claude_model`: "" = CLI 기본(sonnet), "haiku" = 경량 테스트, "opus" = 최고 품질

## 데이터 흐름
- SRT raw_block: 인덱스+타임스탬프+텍스트 (분할 계량 단위)
- cues_to_txt(): "[HH:MM:SS] text" (Claude에 전송되는 포맷, raw_block의 ~50%)
- chunk_max_chars/chunk_max_tokens: raw_block 기준 (cues_to_txt 아님)
- 채팅: work/{video_no}/{video_no}_chat.log → "[HH:MM:SS] user: message" 포맷

## 모델별 비용 참조 (10시간 VOD, API 기준)
| 조합 | 호출 | 입력 토큰 | API 비용 |
|------|------|----------|---------|
| Haiku + 필터링 | 6회 | 180K | $0.18 |
| Haiku + 전체 | 16회 | 554K | $0.54 |
| Sonnet + 필터링 | 6회 | 180K | $0.68 |
| Sonnet + 전체 | 16회 | 554K | $2.07 |
※ Max plan에서는 비용 무관. 시간만 고려하면 됨.

# 컨텍스트
- 프로젝트: C:\github\auto-caption-generator
- Python 3.12, Windows 11
- Claude Code Max plan (claude -p 는 subprocess로 호출됨, API key 없음)
- Anthropic SDK 코드는 있으나 현재 Max plan에서는 비활성 (API key 필요)
- 실험 데이터: work/ 아래 SRT, chat.log 파일
  - 10시간 VOD: work/12752012/ (대용량 테스트)
  - 클립: work/12702452/*_clip1800s.srt (경량 테스트)
```

---

## 사용법

### 권장 A — `/loop` 자율 페이싱 (Claude가 간격을 스스로 결정)

```
/loop Read DEVELOP.md, PIPELINE-BACKLOG.md, PROJECT-RULES.md first. Think hard. DEVELOP.md 규칙대로 1회전만 실행하고 정지. 북극성(관리자/엔드유저 UX 엉망) 상기.
```

- 간격 생략 → 모델이 **ScheduleWakeup**으로 다음 세션 예약 (1분~1시간 클램프).
- 매 회전은 **fresh context의 새 세션** — context 누적·품질 저하 방지.
- 정지: `CronList`로 작업 ID 확인 후 `CronDelete <id>` (또는 Claude에게 "현재 루프 취소해줘").
- **주의 — session-scoped**: Claude Code를 닫거나 새 conversation 시작 시 예약이 사라짐. `--resume`으로 세션 재개해야 유지됨.

### 권장 B — `/loop` 고정 간격 (cron 외부 trigger, 가장 견고)

```
/loop 30m Read DEVELOP.md, PIPELINE-BACKLOG.md, PROJECT-RULES.md first. Think hard. DEVELOP.md 규칙대로 1회전만 실행하고 정지. 북극성(관리자/엔드유저 UX 엉망) 상기.
```

- cron(`*/30 * * * *`)이 외부에서 trigger → 모델이 ScheduleWakeup을 호출하든 말든 무관.
- **7일 후 자동 만료** — 장기 운용 시 주기적 재생성 필요.
- 권장 간격 30m~1h (1회전 보통 10~30분 걸림).
- 놓친 fire는 catch-up 안 됨 (동시 다중 fire 없음).

### 대안 C — 수동 재붙여넣기

1. `# 프롬프트` 블록 전체를 복사해서 붙여넣는다.
2. 1개 백로그/UX 항목 구현 → 커밋 → PR → 머지 후 정지.
3. 마지막 안내가 나오면 다시 붙여넣는다.
4. PIPELINE-BACKLOG.md 모든 항목 `[x]`되어도 북극성(UX) 축이 살아 있으므로 자가발굴로 계속.

### 금지

- **한 세션 안에서 N회전 연속 실행** (프롬프트에 "Continue indefinitely" 추가, 모델이 루프 본문을 다회 반복 등). 품질·토큰 둘 다 망친다.
- **pipeline_config.json / output/ / work/ / .claude/ 커밋**. 아무리 자동 루프여도 예외 없음.

## MVP 완료 후 자동 전환

백로그가 비면 프롬프트가 자동으로:
1. 실제 VOD 30분 처리를 실행하여 새 문제 발견
2. 코드베이스를 점검하여 개선점 도출
3. 새 백로그 항목 추가
4. 다시 루프 시작

## 변경 이력

| 날짜 | 변경 |
|------|------|
| 2026-04-17 | v1 — 초안 작성 |
| 2026-04-17 | v2 — 검증 계층화(Tier 1-4), claude -p 경량 테스트 허용, 아키텍처 참조 추가, 브랜치 정책 명시 |
| 2026-04-17 | v3 — Haiku 전체 청크 테스트 허용, claude_model 설정 추가, PR→merge 자동 워크플로, 모델별 비용표 |
| 2026-04-17 | v4 — 토큰 누수/품질 저하 대응: (1) 1회전 강제 정지·"indefinitely" 금지, (2) Stop-Phrase Guard, (3) Read-First 강화(호출자 1단계 포함), (4) B-항목 1커밋 크기 초과 시 분할, (5) Tier 3 Haiku 상한(단일 청크 3회), (6) 최종 보고 10줄 제한, (7) 프롬프트 상단에 "Think hard / ULTRATHINK" 명시 |
| 2026-04-17 | v5 — 루프 지속성 + UX 축: (1) "1회전 = 1세션" 명시, `/loop` ScheduleWakeup 허용으로 dynamic 모드 가동, (2) 북극성 섹션 신설 — 관리자/엔드유저 UX 엉망이 고정 전제, (3) 상태 파악에 UX 자가발굴(CLI/리포트/설정실패/tray) 루틴 주입, (4) 자기 평가에 "UX 축 좁힘" 한 줄 강제, (5) 사용법을 /loop 공식 동작(자율 페이싱·고정 cron·수동)에 맞춰 재작성 + CronDelete 정지 + session-scoped 주의, (6) 무관 dirty 파일 stash 금지 명시 |
| 2026-04-17 | v5.1 — post-merge cleanup 강제: (1) `gh pr merge` 에 `--delete-branch` 필수, (2) main 복귀 후 `git fetch --prune origin` + gone local branch 일괄 삭제 절차 박음. 기존엔 remote/local 양쪽 브랜치가 누적되어 `git branch -vv` 가시성이 망가지던 이슈 해결. |
