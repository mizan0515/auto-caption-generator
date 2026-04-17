# 00 — Autonomous Dev Loop (All-in-One)

> 이 한 프롬프트만 계속 붙여넣으면 MVP → 완성품까지 자기 구동으로 빌드된다.
> 매 루프 iteration 은 **실제 실행 + 사용자 관점 QA + 기획 수정 + 코드 수정 + PR self-review** 를 포함한다.

## 1. Boot (매 iteration 시작 시)

1. `PROJECT-RULES.md`, `CLAUDE.md`, `DEVELOP.md`, `PIPELINE-BACKLOG.md`, `README.md` 를 먼저 읽는다.
2. `git status` + `git log --oneline -5` 로 현재 상태 파악.
3. 자신이 지금 **어느 단계** 인지 스스로 판단한다:
   - **MVP 단계**: `PIPELINE-BACKLOG.md` 에 `[ ]` 항목이 남아있음 → (2) 로 진행.
   - **Polish 단계**: 백로그 비어있지만 앱 UX/문서/테스트 커버리지에 결함 존재 → (3) 로 진행.
   - **Productization 단계**: 기능 완성 + UX 합격 → (4) 로 진행.

## 2. MVP 단계 — 백로그 소화 루프

매 iteration 당 **정확히 1개** 백로그 항목:

1. 다음 `[ ]` 항목 선택.
2. `git checkout --detach origin/main && git fetch origin && git checkout -b pipeline/bXX-slug origin/main`
3. **구현**. 범위 증식 금지. 필요 모듈만 수정.
4. **Tier 1-3 검증**:
   - Tier 1: `python -c "import <module>"` — import smoke
   - Tier 2: monkeypatch unit — 핵심 분기 커버
   - Tier 3: 실제 assets 로 end-to-end (haiku 모델 사용, 30분 클립)
5. **(앱 대상인 경우) 실제 실행 QA** — 섹션 5 참조.
6. `PIPELINE-BACKLOG.md` 갱신 (`[x]` + 완료 기록 테이블).
7. 섹션 6 의 PR 파이프라인 실행.
8. 섹션 7 의 self-review 실행.
9. 섹션 8 의 스케줄링 실행.

백로그가 비었으면 (3) 으로.

## 3. Polish 단계 — 앱 실행 + UX 결함 자기 발굴

**기본 전제: "현재 앱의 UX 는 이상하다."** 이 전제를 매 iteration 유지한다.
"괜찮아 보인다" 는 금지. 항상 구체적 불편 1개 이상을 뽑아내야 한다.

1. 앱을 실제로 띄운다. 본 저장소의 실행 타겟:
   - `app.py` (Streamlit) — `mcp__Claude_Preview__preview_start` 로 띄운 뒤 브라우저 제어.
   - `gui.py` (tkinter) — subprocess 로 실행 + 스크린샷 (pyautogui 또는 OS 캡처)
   - `tray_app.py` (tray) — 콘솔 런치 + 로그 파싱
   - CLI (`python -m pipeline.main`) — haiku 모델, 30분 클립 end-to-end
2. **직접 제어**:
   - Streamlit: `mcp__Claude_Preview__preview_click` / `preview_fill` / `preview_snapshot` / `preview_screenshot` / `preview_console_logs` / `preview_eval`
   - 브라우저 확장: `mcp__Claude_in_Chrome__browser_batch` (fallback)
   - 모든 상호작용은 **한 user journey = 한 iteration** 단위로 기록.
3. **관찰 체크리스트** (최소 1개 결함 발굴):
   - 첫 화면에서 사용자가 뭘 해야 하는지 10초 안에 감 잡히나?
   - 로딩/에러 상태가 명시적인가? (무한 스피너, 무음 실패 금지)
   - 진행률 피드백 정확한가? (실제 작업 vs 표시 괴리)
   - 파일명/경로 노출이 사람이 읽을 수 있는가?
   - 한글 UTF-8 깨짐 없나?
   - 재실행/취소/되돌리기 동선 있나?
   - 설정값이 런타임에 먹히는가? (`pipeline_config.json` 변경 후 재기동 필요성 명시?)
4. 발굴한 결함을 `PIPELINE-BACKLOG.md` 에 **새 B-item** 으로 추가 (priority + 파일 + 목표 명시).
5. 그 항목을 즉시 구현 (섹션 2 의 4~8 단계 재사용).

## 4. Productization 단계 — MVP 완성 후

이행 조건: 백로그 `[ ]` 0개 + 섹션 3 체크리스트 2 iteration 연속 결함 0건.

1. `docs/` 또는 `README.md` 에 **사용자용 문서** 추가/확장:
   - Quick Start (5분 이내 첫 자막 생성)
   - Feature tour (스크린샷 포함)
   - Troubleshooting (실제 발생했던 에러 기준)
   - Config reference (`pipeline_config.json` 모든 키 의미 + 기본값)
2. **레퍼런스 리서치**: `WebSearch` / `WebFetch` 로 유사 OSS 3+ 개 조사:
   - 쿼리 예: "chzzk vod transcription github", "whisper korean subtitle generator",
     "streamer highlight auto timeline"
   - 각 레포의 README 구조 / 기능 / 라이선스 / 차별화 포인트 정리 → `docs/competitive-scan.md`
3. **릴리즈 준비**:
   - `pyproject.toml` / `requirements.txt` 검증
   - `build.bat` 산출물 (`dist/`) 스모크 (실행 → 자막 1개 생성 → 종료)
   - CHANGELOG 업데이트
   - semver 버전 범프 후 태그
4. 각 하위 작업은 섹션 6~8 파이프라인으로 1개씩 출하.

## 5. 앱 실행 QA 세부 절차

### Streamlit (`app.py` / `pages/`) 기본 흐름
```
1. preview_start  → url 받기
2. preview_snapshot → 구조 파악 (어떤 버튼/입력 있는지)
3. preview_fill / preview_click → 실제 사용자 동선 재현
4. preview_console_logs + preview_network → JS 에러 / 실패 요청 확인
5. preview_screenshot → 시각 회귀 확인 (저장: experiments/ux_captures/<date>_<slug>.png)
6. preview_stop
```

### tkinter (`gui.py`) 기본 흐름
```
1. subprocess.Popen 으로 띄우고 pid 확보
2. pyautogui (Windows) 로 스크린샷 + 좌표 클릭 — 가능하면 위젯 좌표를 로그로 출력해두고 재사용
3. 에러는 stdout/stderr 로 흘러나오도록 환경변수 PYTHONUNBUFFERED=1
```

### 실패 처리
- 앱이 뜨지 않으면 → 그게 **최우선 결함**. 백로그 꼭대기에 추가하고 이번 iteration 에 고친다.
- 콘솔 에러/경고는 전부 기록. "무해해 보인다" 는 평가 금지.

## 6. PR 파이프라인

각 iteration 의 모든 코드/문서 변경은 다음으로 출하:

```
git add <touched files only — never "git add -A">
git commit -m "<scope>: <imperative subject>

<why-not-what, 3-5 lines>

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
"
git push -u origin pipeline/bXX-slug
gh pr create --title "..." --body "<Summary / Findings / Test plan>"
gh pr merge <N> --squash --delete-branch
git fetch origin
git checkout --detach origin/main   # main 은 sibling worktree 가 점유 중
```

절대 금지:
- `main` 직접 push
- `--amend` (이전 커밋 파괴 위험)
- `--no-verify` / 훅 스킵
- `pipeline_config.json`, `output/`, `work/`, 쿠키 커밋

## 7. PR Self-Review (critical)

PR 생성 직후, 다음을 **자기 자신에게** 엄격히 적용:

1. `gh pr diff <N>` 을 다시 읽는다. 마치 **다른 사람의 PR** 인 것처럼.
2. 아래 질문에 1건이라도 "예"가 나오면 추가 커밋으로 수정 후 재푸시:
   - 주석으로만 "처리했다" 고 말하고 실제 코드는 없는 곳이 있는가?
   - 테스트가 production path 와 다른 경로를 탔는가? (happy path only, mock 과다)
   - 에러 메시지가 사용자에게 무의미한가?
   - 새 public 함수에 타입힌트/독스트링 누락?
   - 기존 동작을 조용히 바꿨는데 backlog/README 업데이트 없는가?
   - "TODO" / "FIXME" / dead import / 주석 처리된 코드 남았는가?
   - 성능 회귀 가능성 (N+1, 전체 파일 재파싱, 반복 네트워크 호출)?
   - 설정 키를 추가했는데 `DEFAULT_CONFIG` / `pipeline_config.json` 스키마 동기화 안 됨?
3. 문제가 발견되면: 같은 PR 브랜치에 **추가 커밋** (amend 금지). 다시 self-review.
4. 완전 clean 으로 끝나는 self-review 는 허용하되, **구체적 근거 3줄 이상** 으로 "왜 clean 한지" 명시.
   "LGTM" / "문제 없음" 단독 금지.

## 8. Scheduling (매 iteration 종료)

마지막으로 **반드시** `ScheduleWakeup` 을 호출한다:

- `delaySeconds`: 60 (다음 iteration 바로 착수) 또는 가장 느린 외부 신호까지의 대기 시간
- `prompt`: `/loop Read .prompts/00-autonomous-dev-loop.md and execute one iteration. Continue indefinitely.`
- `reason`: 한 문장으로 다음 iteration 의 타겟 명시 (예: "B13 chunk_max_chars sweep 다음 이터레이션")

루프를 멈추는 유일한 방법은 사용자의 명시적 중단 지시 또는 **합리적 종료 조건 (릴리즈 태그 발행 완료)** 발생. 이 두 경우 외에는 무조건 다음 wakeup 을 스케줄한다.

## 9. 보고 형식 (각 iteration 마지막 메시지)

사용자에게 6줄 이내로 보고:
```
✅ <scope>: <무엇을 했는지 한 줄>
PR #N merged (commit <sha>)
UX QA: <발견한 결함 1줄 or "N/A (backlog item)">
Self-review: <clean or 추가 커밋 개수>
다음: <다음 iteration 타겟>
Wakeup scheduled in Ns
```

---

## 금기 사항 요약

- 🚫 "아마 괜찮을 것이다" / "LGTM" / "큰 문제 없어 보인다"
- 🚫 실행 없이 QA 보고
- 🚫 사용자 관점 점검 없이 "기능 동작" 으로 패스
- 🚫 PR self-review 생략
- 🚫 다음 wakeup 스케줄 누락
- 🚫 한 iteration 에 2개 이상 scope 섞기

## 확장

새 단계 / 새 체크리스트가 필요하면 **이 파일을 직접 수정** 하고 같은 iteration 에서 커밋.
루프 자체의 진화도 루프의 일부다.
