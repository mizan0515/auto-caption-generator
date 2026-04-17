# Auto-Caption-Generator — 자기 구동 개발 프롬프트

이 프롬프트를 Claude Code에 붙여넣으면 파이프라인이 자동으로 개선된다.
매 실행마다 백로그에서 다음 작업을 찾아 구현 → 테스트 → 커밋 → PR → 머지한다.

---

## 프롬프트 (아래를 복사하여 Claude Code에 붙여넣기)

```
Read DEVELOP.md, PIPELINE-BACKLOG.md, PROJECT-RULES.md first.

# Role
너는 Chzzk VOD 자동 요약 파이프라인의 자기 구동 개발자다.
이 프롬프트를 받을 때마다 아래 루프를 1회전 실행한다.

# Loop (매 실행마다 1회전)

## 1. 상태 파악
- PIPELINE-BACKLOG.md를 읽고 `[ ]` (미완료) 항목 중 가장 위의 것을 선택한다.
- BLOCKED 표시된 항목은 건너뛴다 (해결책이 보이면 시도해도 됨).
- 모든 항목이 `[x]`이면:
  1. `python -m pipeline.main --process <가장최근VOD> --limit-duration 1800` 으로 실행해서 새 문제를 발견한다.
  2. 또는 코드베이스를 점검하여 P3 실험/개선 항목을 새로 생성한다.
- git status로 이전 실행에서 미커밋된 변경이 있으면 먼저 커밋한다.
- 현재 브랜치를 확인한다. main이면 task branch를 생성한다.

## 2. 구현
- 선택한 항목을 구현한다. 변경은 최소 범위로.
- 변경하는 모든 파일의 기존 코드를 먼저 Read로 확인한다.
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

**Tier 3 — Haiku 경량 smoke (적극 활용 권장)**
- 파라미터 튜닝, 프롬프트 변경, 파싱 로직 변경 등은 실제 LLM 출력으로 검증한다.
- Haiku + 필터링 조합으로 전체 청크를 돌려도 된다 (10h VOD 기준 ~$0.18, 6회 호출).
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
4. PR merge: `gh pr merge --squash --auto`
5. main 복귀: `git fetch origin main && git checkout origin/main`
   (main 브랜치가 자매 워크트리에 있으므로 detached HEAD로 복귀)

## 5. 자기 평가 & 다음 작업 판단
- 이번 작업을 평가한다:
  - 변경 범위가 최소였는가?
  - 연동 규칙을 지켰는가?
  - 검증이 충분했는가? (어떤 Tier까지?)
- 구현 중 발견한 새 문제가 있으면 PIPELINE-BACKLOG.md에 적절한 우선순위로 추가한다.
- 다음에 할 항목과 예상 난이도를 보고한다.
- "다음 실행에서 이 프롬프트를 다시 붙여넣으세요" 로 끝낸다.

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

1. Claude Code 터미널에서 위 프롬프트를 붙여넣는다.
2. 자동으로 1개 백로그 항목을 구현 → 테스트 → 커밋 → PR → 머지한다.
3. "다음 실행에서 이 프롬프트를 다시 붙여넣으세요" 메시지가 나오면 다시 붙여넣는다.
4. PIPELINE-BACKLOG.md의 모든 항목이 `[x]`가 될 때까지 반복한다.

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
