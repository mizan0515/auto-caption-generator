# Shared Project Rules — auto-caption-generator

이 문서는 Codex와 Claude Code 모두에 적용되는 저장소 공통 규칙이다.
DAD v2 도입 시점(2026-04-14)에 작성됨. 변경 시 같은 작업에서 문서 동기화한다.

## Source Of Truth

문서가 충돌하면 아래 우선순위를 따른다:

1. **live 코드** — `pipeline/`, `transcribe.py`, `tray_app.py`, `content/network.py`
2. **`pipeline_config.json`** — 런타임 설정 권위. `pipeline/config.py`의 `DEFAULT_CONFIG`가 baseline
3. **`prompts/청크 통합 프롬프트.md`** — Claude 최종 통합 요약 프롬프트의 권위 텍스트
4. **`README.md`** — 사용자/운영자 관점 진입 문서
5. **`experiments/results/`** — 파라미터 결정 근거 (예: `experiments/results/progress_report.md`, `experiments/results/summary.md`)
6. **`Document/`** — DAD 운영 문서 + 세션 산출물

추가 기대치:

- live 파일이 stale summary나 chat 메모와 충돌하면 live 파일을 우선한다.
- 하위 우선순위 문서가 상위 정의 용어를 재정의해서는 안 된다.
- stale summary를 발견하면 가능한 한 같은 작업에서 갱신한다.

## Current Repository Reality

이미 존재하는 모듈:

- `pipeline/` — 자동 모니터링 파이프라인 (config, monitor, downloader, chat_collector, chat_analyzer, transcriber, chunker, scraper, claude_cli, summarizer, subtitle_analyzer, community_matcher, main, settings_ui, state, utils, models)
- `content/network.py` — Chzzk DASH/m3u8 매니페스트 + 메타데이터 (Qt 의존성 없는 static 메서드)
- `transcribe.py` — Whisper large-v3-turbo + Silero VAD 자막 생성 코어 (GUI 분리된 콜백 인터페이스)
- `split_video.py` — ffmpeg 영상 분할
- `tray_app.py` — Windows 시스템 트레이 런처
- `merge.py` — (구 도구) MP4 병합
- `experiments/` — 파라미터 튜닝 실험 스크립트와 결과 (`experiments/chunk_size_experiment.py`, `experiments/test_html_render.py`, `experiments/test_parser.py`, `experiments/results/summary.md`, `experiments/results/progress_report.md`)
- `prompts/청크 통합 프롬프트.md` — Claude 통합 요약 템플릿
- `_archive/` — 이전 프로젝트 (Streamlit `app.py`, GUI 등) — 참고용. **새 작업의 source-of-truth가 아니다.**

런타임 전제:

- Python 3.10+, ffmpeg PATH 등록, Claude Code CLI(`claude`) 설치
- CUDA GPU 권장 (Whisper 가속)
- Windows 우선. PowerShell 5.1 또는 pwsh 7.2+
- `.claude/settings.local.json`은 Claude Code 권한 허용 목록을 보유 (커밋 안 함, gitignore됨)

stale 가능성:

- `Document/` 산하 모든 운영 문서는 신규 도입(2026-04-14)이라 아직 live 세션 산출물 없음.
- `_archive/` 내 모든 파일은 갱신 책임이 없다. 참고만.

용어 혼동 방지:

- **"prompts/" (점 없음)** = Claude 통합 요약 프롬프트 (런타임 자산)
- **".prompts/" (점 있음)** = DAD v2 운영 프롬프트 라이브러리 (메타 자산)
- **"transcribe"** = Whisper 자막 생성 (≠ chat collection)
- **"hot_segment"** = 커뮤니티-자막 키워드 교차 (≠ chat peak)

## Project Facts

- 제품 유형: 스트리머 VOD 자동 모니터링 + AI 요약 파이프라인
- 현재 마일스톤: 멀티-시그널 하이라이트 + A1/A2(Claude 토큰 로깅, token chunking) 완료 후 A3 재측정 대기 상태 (참조 — experiments/results/progress_report.md, experiments/results/2026-04-14_phase-a1_token-logging.md, experiments/results/2026-04-15_phase-a2_token-chunking.md)
- 메인 아키텍처 경계:
  - `pipeline/main.py` 오케스트레이터 ↔ 각 단계 모듈 (모듈 간 import 단방향)
  - `pipeline/state.py` 가 처리 상태 권위 (`output/pipeline_state.json`)
  - `pipeline_config.json`이 런타임 설정 권위 (cookies 포함, **gitignored**)
- 비밀 자산: Chzzk `NID_AUT`, `NID_SES` 쿠키 — 절대 커밋 금지
- 데이터 경로: `output/` (리포트), `work/` (임시) — gitignored

## Guardrails

다음 규칙은 모든 에이전트가 보존한다:

- `pipeline_config.json`, `output/`, `work/`, `_archive/`, `.claude/`(commands 제외) 는 git 추적 금지
- Chzzk 쿠키(`NID_AUT`, `NID_SES`)는 코드/로그/문서 어디에도 평문 노출 금지
- `pipeline/config.py`의 `DEFAULT_CONFIG`가 신규 사용자의 baseline. 키 추가/제거는 호환성 확인 후
- `prompts/청크 통합 프롬프트.md`의 출력 포맷 규칙은 깐깐하다 — 변경 시 `pipeline/summarizer.py`의 `_parse_summary_sections()` 정규식과 동기 필요
- `pipeline/summarizer.py` ↔ `_generate_html()` ↔ MD 파서 3자는 한 단위로 변경
- `_archive/` 내 코드를 import하지 않는다 (참고만)
- `transcribe.py`는 GUI/CLI 양쪽에서 호출되므로 시그니처 변경 시 `tray_app.py`, `pipeline/transcriber.py` 둘 다 점검
- 멀티-시그널 하이라이트 (chat / subtitle / community) 3축 중 하나만 변경해도 `pipeline/summarizer.py`의 `merge_results` 함수 프롬프트 컨텍스트 검증

## Verification Expectations

- **최소 검증**: 변경한 모듈이 import만 되는지 (`python -c "from pipeline.X import ...; print('ok')"`)
- **파라미터 변경**: `experiments/`에 측정 스크립트 추가하고 `experiments/results/`에 결과 + 결정 근거 기록
- **요약 포맷 변경**: `experiments/test_parser.py`, `experiments/test_html_render.py`로 회귀 점검
- **claude CLI 호출 경로 변경**: 30분 클립 1개 종단 실행으로 smoke (`output/`에 md/html/json 3개 생성 확인)
- **막힌 검증 보고**: 종단 실행이 크리덴셜/네트워크/GPU 부재로 막히면 명시적으로 보고하고 부분 검증 결과 첨부
- **충분한 근거**: "looks good" 금지. 파일 경로 + 라인 + 전후 값 명시

## DAD Operating Reality

- **세션 우선 모드**: hybrid (대다수 작업), supervised (DAD 인프라/계약 변경 시), autonomous (소규모 버그픽스)
- **세션 슬라이스**: 짧은 session-scoped slice 우선. 한 작업 = 한 세션 권장. 목표/검증 표면 바뀌면 새 세션
- **제품 우선 원칙**: DAD는 실제 제품 진전(측정, 수정, 실행, smoke, config 판단)에 우선 사용한다. 운영 메타작업은 부수 처리여야 한다.
- **한 세션 = 실제 산출 1개**: 기본 단위는 측정 결과 1개, 버그 수정 1개, smoke 1개 같은 concrete output이다. state/summary 정리만을 위한 세션 개설은 지양한다.
- **관리성 턴 최소화**: wording correction, closure seal, 이미 닫힌 사실의 재확인만을 위한 턴은 기본 금지에 가깝게 다룬다. 같은 턴에서 닫을 수 있는 documentary drift는 그 턴 안에서 끝낸다.
- **peer-verify 제한 사용**: remote-visible mutation, runtime/config decision, high-risk measurement처럼 실제 리스크가 큰 경우에만 별도 peer-verify 턴을 둔다. 저위험 문구/메타 정리는 실행 턴 안에서 같이 닫는다.
- **세션 종료 전 필수 validator**: `tools/Validate-Documents.ps1`, `tools/Validate-DadPacket.ps1` (live 세션 있을 때)
- **부트스트랩 점검**: `pipeline_config.json` 존재 여부, ffmpeg/claude CLI PATH, GPU 가용성
- **summary 갱신**: 세션 종료 시 `Document/dialogue/sessions/{session-id}/summary.md` 작성. 운영 의미 있는 결정은 `experiments/results/`에도 사본 (운영 보고서 흐름)

운영 경고:

- DAD를 DAD 관리 자체에 쓰기 시작하면 토큰과 시간이 빠르게 샌다.
- 아래는 **나쁜 DAD 패턴**으로 취급한다:
  - 실행 세션 뒤에 peer-verify only, wording-fix only, final-seal only 세션을 연쇄로 여는 것
  - 이미 `converged`인 사실을 반복 확인하는 것
  - state/summary 동기화가 본체가 되는 세션
- 아래는 **좋은 DAD 패턴**으로 권장한다:
  - W1/W2/W3 재측정
  - 실사용 smoke
  - summarizer/parser 버그 수정
  - 다운로드/채팅 수집 실패 원인 수정
  - UI/트레이 사용성 개선

## Git Rules

- **현재 브랜치**: `main` (단독 개발자, task branch 정책 미적용)
- **권장**: DAD 계약 변경, 파이프라인 구조 변경 등 큰 작업은 task branch에서 작업 후 PR
- **금지**:
  - 검증 없이 main에 직접 push
  - `pipeline_config.json` 커밋
  - Chzzk 쿠키 커밋
- **dirty file 차단 보고**: 무관한 modified 파일이 staging을 막으면 그 사실을 명시적으로 보고하고, 사용자 승인 없이 stash/reset 안 함
- **DAD 도입 이후 첫 권장**: 본 도입 작업과 무관한 11개 modified 파일(2026-04-14 기준)이 working tree에 있음 → 별도 commit으로 분리 권장
