# Pipeline Improvement Backlog

최종 갱신: 2026-04-17. 이 문서는 자기 구동형 개발 프롬프트(`DEVELOP.md`)의 작업 목록이다.
각 항목은 독립적으로 구현/테스트 가능한 단위다.
완료 시 `[x]`로 표기하고 검증 결과를 한 줄로 기록한다.

## 우선순위 P0 — 토큰 효율 (즉시)

- [x] **B01 채팅 하이라이트 기반 자막 필터링**
  - 파일: `pipeline/chunker.py`, `pipeline/main.py`
  - 현상: 10시간 VOD의 자막 244,389자가 전부 Claude에 전송됨
  - 목표: 채팅 하이라이트 ±N분은 상세, 나머지는 30초당 1줄 샘플링
  - 파라미터: `highlight_radius_sec` (기본 300=5분), `cold_sample_sec` (기본 30)
  - 기대: 244K자 → ~100K자 (60% 절감), 호출 15회 → 6회
  - 검증: 실제 SRT + 채팅으로 필터 전후 크기 비교, 시간 커버리지 100% 확인
  - 주의: 필터링 후에도 전체 시간축이 빠짐없이 표현되어야 함 (cold 구간도 샘플 포함)

- [x] **B02 chunk prompt에서 내부 메트릭 제거**
  - 파일: `pipeline/summarizer.py`
  - 현상: merge 프롬프트에 "채팅수 {count}, 종합점수 {composite:.4f}" 포함
  - 문제: Claude 지시문이 "내부 메트릭 노출 금지"라고 하면서 프롬프트에서 메트릭을 주입
  - 목표: highlight 정보를 타임코드 + 설명적 표현으로 변환

- [x] **B03 전체 채팅 리스트 반복 필터링 제거**
  - 파일: `pipeline/main.py`, `pipeline/summarizer.py`
  - 현상: process_chunks()에 50K개 채팅 전체를 전달 → 매 청크마다 전체 스캔
  - 목표: main.py에서 청크별 채팅을 미리 슬라이싱하여 전달

## 우선순위 P1 — 안정성 (중요)

- [x] **B04 find_edit_points 에러 핸들링**
  - 파일: `pipeline/main.py:199`
  - 현상: 채팅 분석 실패 시 전체 파이프라인 크래시
  - 목표: try/except로 감싸고 빈 highlights로 fallback

- [x] **B05 Whisper 실행 타임아웃/에러 핸들링**
  - 파일: `pipeline/transcriber.py`
  - 현상: Whisper가 행(hang) 걸리면 무한 대기
  - 목표: 타임아웃 설정 + 에러 시 graceful 실패

- [x] **B06 다운로더 bare pass 제거**
  - 파일: `pipeline/downloader.py:107-115`
  - 현상: 다운로드 실패를 조용히 무시, 불완전 파일 남김
  - 목표: 실패 시 파일 정리 + 명시적 에러 발생

- [x] **B07 실패 VOD 재시도 시 스트리머별 설정 유실**
  - 파일: `pipeline/main.py:393`
  - 현상: 재시도 시 글로벌 cfg 사용 → 스트리머별 검색 키워드 무시
  - 목표: failed_vods에 channel_id 저장 → 재시도 시 해당 스트리머 cfg 복원

## 우선순위 P2 — 품질 (개선)

- [x] **B08 SRT 반복 파싱 제거**
  - 파일: `pipeline/summarizer.py:197-212`
  - 현상: find_subtitle_peaks()와 build_community_signal()이 각각 parse_srt() 호출
  - 목표: cues를 한 번 파싱하고 두 함수에 전달

- [x] **B09 HTML 파싱 fallback 강화**
  - 파일: `pipeline/summarizer.py:383-497`
  - 현상: Claude 출력이 예상 포맷에서 벗어나면 파싱 실패 → 빈 타임라인
  - 목표: 유연한 파싱 + 항상 raw_fallback 유지

- [x] **B10 FM코리아 세션 재사용**
  - 파일: `pipeline/scraper.py:268-273`
  - 현상: 매 scrape마다 세션 생성 + 메인 페이지 방문
  - 목표: 데몬 모드에서 세션 재사용

- [x] **B11 오래된 VOD FM코리아 자동 스킵**
  - 파일: `pipeline/main.py`, `pipeline/scraper.py`
  - 현상: 20일 전 VOD도 FM코리아 검색 시도 → 의미없는 네트워크 호출
  - 목표: VOD publish_date가 48시간 이전이면 fmkorea 스킵

## 우선순위 P0.5 — UX 결함 (Polish 단계 자가발굴)

- [x] **B22 머지 실패 리포트 prompt leak + 복구 가이드 부재**
  - 파일: `pipeline/summarizer.py`, `experiments/b22_merge_failure_ux.py` (신규)
  - 현상: `output/12402235_...md` 가 `"## chunk_01 — 분석 실패: Claude CLI 실패 (code=1): 알 수 없는 오류"` 뒤에
    `"해당 구간은 건너뛰고 요약해주세요"` 라는 **LLM-facing 지시문**을 그대로 노출. 이는 원래 Claude
    에게 보낼 머지 프롬프트에 prepend 하던 문구인데, merge_results/two_round_merge 의 fallback
    경로가 `all_results` 를 그대로 반환 → 사용자 리포트에 프롬프트 유출. 게다가 `"알 수 없는 오류"`
    말고는 재시도 방법/로그 위치 안내가 전혀 없어 엔드유저가 뭘 해야 할지 모름.
  - 목표: (a) LLM 지시문과 사용자 배너 분리 (`_format_failure_notice_for_llm` + `_build_failure_report`),
    (b) fallback 시 실패 원인 요약(traceback 숨김) + `--process <video_no>` 재실행 명령 + 로그 위치 안내,
    (c) 성공 청크 0건/전체 실패 모두 커버.
  - 검증: `experiments/b22_merge_failure_ux.py` 7 케이스 (성공/실패 머지 × 실패 청크 유무, helper
    단독, reason 다중줄 traceback 숨김).

- [x] **B23 `--config` CLI 인자가 load_config() 에서 무시되던 silent override 제거**
  - 파일: `pipeline/config.py`, `pipeline/main.py`, `experiments/b23_config_path_arg.py` (신규)
  - 현상: `pipeline/main.py` 는 argparse 로 `--config` 경로를 받지만 그 뒤 `cfg = load_config()`
    를 **무인자로** 호출. 결과적으로 사용자가 `python -m pipeline.main --config prod.json`
    으로 명시 지정해도 조용히 기본 `pipeline_config.json` 이 로드된다. help 에는 "설정 파일
    경로 (기본: pipeline_config.json)" 이라 약속되어 있어 silent override UX 최악.
    B21 의 `ConfigError` 메시지도 `_config_path()` 기본 경로만 찍고 있어 "어느 파일이 틀렸는지"
    까지 오도하는 2차 결함.
  - 목표: (a) `load_config(config_path=None)` / `save_config(..., config_path=None)` 도입,
    커스텀 경로를 실제로 사용, (b) `validate_config(..., source_path=...)` 로 오류 메시지에
    실제 파일 경로 노출, (c) 없는 경로에는 기존 동작(DEFAULT 자동 생성)을 그 경로로 적용.
  - 검증: `experiments/b23_config_path_arg.py` 7 케이스 (기본 None 경로/커스텀 경로 값 반영/
    없는 경로에 DEFAULT 저장/커스텀 경로 save/ConfigError 메시지에 실제 경로 포함/
    상대→절대 resolve/save→load 왕복). B21 회귀(13/13) 도 동시 유지.

## 다음 회전 후보 (v5.3 브레인스토밍 밑천)

- [ ] **B-ux-next tray_app KeyboardInterrupt 안내 부재** — Ctrl+C 시 tray 스레드 종료 경로와 "daemon 을 어떻게 끄는가" 안내 부재 재현/수정
- [ ] **B-quality-next 타임라인 시간 포맷 일관성** — MD/HTML 리포트에서 `[HH:MM:SS]` vs `[MM:SS]` 혼재 여부 실측 후 정규화
- [ ] **B-static-next transcribe.py --cleanup 실동작 검증** — 플래그 존재하지만 호출 흐름에서 실제 동작하는지 smoke
- [ ] **B-websearch-next claude CLI code=1 원인 분류** — WebSearch 로 code=1 대표 원인(인증 만료/네트워크/토큰 한도) 좁힌 후 친절 에러 메시지 매핑 백로그화
- [ ] **B-ux-next2 tray _on_quit 가 daemon 스레드 join 안 함** — process_vod 중 종료 시 강제 단절로 work/ 잔재 + 다음 실행 재다운로드. pipeline_state 쓰기는 atomic(B06 영역)이지만 downloader 중단 파일 cleanup 미확인. stop flag → 최대 N초 대기 → 타임아웃 시 경고 notify 패턴 설계
- [x] **B25 tray 이중 실행 silent race 제거**
  - 파일: `tray_app.py`, `experiments/b25_tray_single_instance.py` (신규)
  - 현상: `tray_app.exe` 를 두 번 실행하면 두 daemon 스레드가 같은
    `pipeline_state.json` 을 경쟁 쓰기 → 중복 다운로드/상태 오염/트레이 아이콘 2개.
    아무 경고 없음 — admin UX 최악의 silent failure 유형.
  - 목표: (a) `output_dir/pipeline.tray.lock` 에 PID 기록 + 이미 살아 있는
    PID 면 `AlreadyRunningError` 로 차단, (b) 교차 플랫폼 `_pid_alive`
    (Windows OpenProcess+GetExitCodeProcess, POSIX `os.kill(pid, 0)`),
    (c) stale/손상 lockfile 은 자동 회수, (d) `_on_quit` 에서 lock 해제
    (멱등), (e) `main()` 이 `AlreadyRunningError` 포획 → MessageBox
    + `SystemExit(3)` (B24 ConfigError exit 2 와 차별).
  - 검증: `experiments/b25_tray_single_instance.py` 11 케이스 (pid_alive 3종/
    lock 신규·stale·live·self·손상 5종/release 멱등/main 대화상자/B24 회귀).
    B24 7/7 + B23 7/7 + B21 13/13 회귀 유지.

- [x] **B24 tray_app ConfigError unhandled**
  - 파일: `tray_app.py`, `experiments/b24_tray_config_error.py` (신규)
  - 현상: `PipelineTray.__init__` 가 `load_config()` 를 호출하는데 잘못된 `pipeline_config.json`
    이 주어지면 B21 의 `ConfigError` traceback 이 날것으로 터짐. 트레이는 GUI 서비스 런처라
    콘솔 traceback 이 보이지 않는 환경에서 조용히 죽는 것과 다름없음.
  - 목표: (a) `main()` 에서 `ConfigError` 만 포획 (RuntimeError 등은 그대로 전파), (b)
    Win32 `MessageBoxW` 로 사용자에게 에러 원문 표시 (tkinter 의존 추가 없이 ctypes 로),
    (c) 비-Windows/ctypes 실패 시 stderr 폴백, (d) `SystemExit(2)` 로 종료.
  - 검증: `experiments/b24_tray_config_error.py` 7 케이스 (ConfigError→exit2, 에러 원문 전달,
    RuntimeError 전파 유지, happy path run() 호출, 비-win32 stderr 폴백, ctypes import 실패
    폴백, multi-line 메시지 전달). B23 7/7 + B21 13/13 회귀 유지.


- [x] **B14 CLI 한글 깨짐 (Windows cp949 stdout)**
  - 파일: `pipeline/main.py`
  - 현상: `python -m pipeline.main --help` 의 한글 description/help 가
    Windows 콘솔 (cp949) 에서 `"실행"→"����"` 등 전부 깨짐. 신규 사용자
    첫 화면이 글자 깨짐 → first impression 0점.
  - 원인: argparse 텍스트가 UTF-8 인데 stdout 인코딩이 cp949.
  - 목표: `pipeline/main.py` 진입 직후 `sys.stdout.reconfigure(encoding="utf-8")`
    (가능한 경우) 적용. CLI/데몬 양쪽 안전.
  - 검증: `python -m pipeline.main --help` 출력에 깨진 글자 0개.

- [x] **B21 pipeline_config.json early type/value validation**
  - 파일: `pipeline/config.py`, `pipeline/main.py`, `experiments/b21_config_validation.py` (신규)
  - 현상: `load_config()` 는 `{**DEFAULT_CONFIG, **user_json}` 로 dict merge 만 하고
    타입/값 검사를 전혀 하지 않는다. 사용자가 `"claude_model": "haiko"` 같은 오타를
    내거나 `"poll_interval_sec": "300"` 같이 문자열을 넣어도 파이프라인이 그대로
    시작되어 다운로드(수백 MB) + Whisper 전사(수십 분) 를 다 돌린 뒤 Claude 호출
    단계 혹은 더 깊은 곳에서 해독 불가능한 traceback 으로 죽는다.
    관리자·신규 사용자의 첫 실행 UX 를 망치는 대표 결함.
  - 목표: `validate_config()` 에서 (a) 숫자 필드 타입·양수 조건, (b) `claude_model`
    enum(`"" / haiku / sonnet / opus`), (c) `bootstrap_mode` enum, (d) `cookies` dict,
    (e) `fmkorea_search_keywords` list 를 검사하고 실패 시 `ConfigError` 로 모든
    오류를 한꺼번에 보고. `pipeline/main.py` 는 traceback 없이 친절한 한국어
    메시지를 출력하고 `sys.exit(2)`.
  - 검증: `experiments/b21_config_validation.py` 13 케이스 (happy path, 각 enum/타입
    오류, 0/음수 경계, bool 이 int 로 오통과하지 않는지, 다중 오류 aggregate,
    `load_config()` 전파 포함).

- [x] **B16 .prompts/00-autonomous-dev-loop.md doc drift 제거**
  - 파일: `.prompts/00-autonomous-dev-loop.md`
  - 현상: §3 step 1, §5 가 존재하지 않는 `app.py` (Streamlit) / `gui.py`
    (tkinter) 를 user-facing entrypoint 로 나열. 실제는 `_archive/` 에만
    존재하는 legacy. Polish iteration 첫 부팅에서 self-misleading.
  - 목표: 실재하는 entrypoint (CLI `python -m pipeline.main`, transcribe.py,
    tray_app.py, 정적 `site/`) 로 교체. QA 흐름도 실제 가능한 방식으로 재기술.
  - 검증: `grep app.py|gui.py` 결과 0건 (tray_app.py 만 정상 잔존).

- [x] **B15 transcribe.py / tray_app.py 동일 cp949 결함 + DRY 헬퍼**
  - 파일: `transcribe.py`, `tray_app.py`, `pipeline/_io_encoding.py` (신규)
  - 현상: B14 와 동일한 한글 깨짐이 `python transcribe.py --help`,
    `python tray_app.py` 콘솔 메시지에서도 발생.
  - 목표: `pipeline/_io_encoding.force_utf8_stdio()` 헬퍼 추출 후 3개
    entrypoint (pipeline.main / transcribe / tray_app) 모두 호출. B14
    인라인 코드도 헬퍼로 교체.
  - 검증: 3개 entrypoint --help 또는 syntax compile 모두 한글 정상.

## 우선순위 P1 — 안정성 (자가발굴)

- [x] **B20 _io_encoding 회귀 테스트 추가**
  - 파일: `experiments/b20_io_encoding_tests.py` (신규)
  - 현상: B14/B15 에서 도입된 `pipeline/_io_encoding.force_utf8_stdio()` DRY
    헬퍼가 3개 entrypoint + 전체 실험 스크립트에서 사용되지만 전용 회귀
    테스트가 없음. reconfigure 폴백 경로 (pythonw/리다이렉트/구버전 Python)
    가 조용히 부서져도 감지 불가.
  - 목표: 7 케이스 오프라인 테스트 (sys.stdout/stderr monkeypatch).
  - 검증: happy_path / None 스트림 / reconfigure 미지원 / OSError / ValueError /
    멱등성 / 실제 io.TextIOWrapper 전환.

- [x] **B19 subtitle_analyzer quote_count 중복 집계 버그 수정**
  - 파일: `pipeline/subtitle_analyzer.py:70`
  - 현상: `_score_text()` 의 인용문 집계 라인이
    `text.count('"') // 2 + text.count('"') // 2 + text.count("'") // 2`
    으로 ASCII `"` 를 두 번 집계 (복붙 오타). ASCII 쌍따옴표 1쌍에 대해
    `quotes=2` 로 과다 집계되어 score +=1.0 (정확히는 +0.5 이어야 함).
    동시에 Unicode curly quotes (U+201C/U+201D, U+2018/U+2019) 는
    전혀 집계되지 않아 실제 한국어 자막의 대사 인용이 누락됨.
    => 자막 기반 하이라이트 peak 선정에 편향 발생.
  - 목표: ASCII 와 Unicode curly quotes 를 각각 올바르게 1회씩 집계.
  - 검증: `experiments/b19_quote_count_typo.py` 로 ASCII 1쌍/2쌍, curly 1쌍,
    혼합, single+curly single 혼합, 인용 없음, 홀수 개 + score 회귀 8 케이스.

- [x] **B18 claude_cli subprocess FileNotFoundError/OSError 가드**
  - 파일: `pipeline/claude_cli.py:236-244`
  - 현상: `_call_claude_cli()` 가 `shutil.which("claude")` 로 선행 체크 후
    `subprocess.run()` 을 호출하지만, (a) TOCTOU (체크와 실행 사이 삭제),
    (b) Windows 에서 `.cmd`/`.bat` shim 과 `.exe` 전환, (c) 실행 권한 손상
    등으로 실제 실행 순간에 `FileNotFoundError` / `PermissionError` 가 발생
    가능. 현재 retry 데코레이터는 `(RuntimeError, TimeoutExpired)` 만 잡으므로
    이런 예외는 그대로 전파돼 파이프라인을 난해한 traceback 으로 중단시킴.
  - 목표: `subprocess.run` 호출을 `try/except FileNotFoundError / OSError` 로
    감싸고 사용자 친화적 메시지를 가진 `RuntimeError` 로 변환. 기존
    `TimeoutExpired` 전파 경로는 보존 (retry 대상).
  - 검증: `experiments/b18_claude_cli_oserror_guard.py` 로 5 케이스 오프라인
    검증 (FileNotFound race / PermissionError / 일반 OSError / which 미설치
    baseline / TimeoutExpired passthrough).

- [x] **B17 m3u8 해상도 파서 IndexError 방어**
  - 파일: `content/network.py:138-145`
  - 현상: `get_video_m3u8_base_url()` 의 `for i, line in enumerate(content)` 루프에서
    RESOLUTION 매칭 라인이 m3u8 응답의 마지막 라인인 경우 `content[i + 1]` 접근이
    `IndexError` 로 크래시. Chzzk 가 EOL 줄바꿈 없이 마지막 스트림을 보내거나
    잘린 응답이 들어올 때 복구 불가능한 예외로 파이프라인 중단.
  - 목표: `i + 1 >= len(content)` 와 빈 문자열 경로를 명시적 `ValueError` 로 변환.
    호출자는 기존에도 `ValueError("해상도 스트림을 찾을 수 없습니다")` 를 처리 중.
  - 검증: `experiments/b17_m3u8_indexerror_guard.py` 로 happy path + trailing
    RESOLUTION + 빈 경로 + 미매칭 4 케이스 오프라인 검증 (requests.get monkeypatch).

## 우선순위 P3 — 실험/튜닝

- [x] **B12 하이라이트 필터 파라미터 최적화 실험**
  - highlight_radius_sec: [180, 300, 420, 600]
  - cold_sample_sec: [15, 30, 60]
  - 측정: 필터 후 자수, 요약 품질 (타임라인 항목 수, 시간 커버리지), 호출 수
  - 기준: 전체 방송 시간의 80% 이상 타임라인에 표현되어야 함
  - 결과: 30분 클립은 차이 미미 (highlight 10개 → 자막의 70%가 hot zone),
    3시간 클립에서 radius=180s + cold=60s 가 70.4% 절감 + 커버리지 98.3% 로 최적.
    풀 VOD 검증 권장.

- [x] **B13 chunk_max_chars 최적화 실험**
  - 후보: [15000, 20000, 30000, 50000]
  - 측정: 타임아웃 발생 여부, 요약 밀도(항목/시간), 총 호출 수
  - 결과: 30분 클립은 영향 없음 (단일 청크). 3시간 클립 + B12 추천 필터에서
    chunk_max_chars=15000 이 risk=low + 청크 2개로 최적. 50000 은 chars_max
    22K 단일청크 (medium risk). 풀 VOD + 실호출 검증 권장.

## 우선순위 P1 — 안정성 (자가발굴, 2026-04-25)

- [x] **B26 fmkorea 430 재발 방지 강화**
  - 파일: `pipeline/scraper.py`, `pipeline/config.py`, `pipeline/main.py`
  - 현상: VOD 12890507 처리 중 fmkorea 430 발생 → 수동 브라우저 수집으로 우회
  - 조치:
    - User-Agent 5종 로테이션 (세션 신규 생성 시 random.choice) → fingerprint 분산
    - 요청 간격 5~7.5s → 8~12s 로 상향
    - 차단 감지 시 `work/<video_no>/.fmkorea_cooldown` 마커 생성 → 3시간 스킵
    - `scrape_fmkorea(work_dir, scraper_mode)` 시그니처 확장
  - 부작용: 키워드당 3페이지 기준 총 수집 시간 ~20초 증가 (전체 파이프라인 5h 대비 무시)
  - 회귀: manual JSON 우선 경로 (`load_manual_community_posts`) 유지, 기존 FmkoreaBlocked/reset_fmkorea_session 동작 유지

- [x] **B27 fmkorea 스크랩 백엔드를 Chromium(Playwright) 로 전환 (옵션)** — 완료 기록 참조

## 완료 기록

| ID | 완료일 | 검증 | 비고 |
|----|--------|------|------|
| B01 | 2026-04-17 | ✅ 10h VOD: 377K→124K chars (67% 절감), 13→5 chunks, 시간커버리지 유지 | chunker.py + main.py + config.py |
| B02 | 2026-04-17 | ✅ Tier2: 메트릭 누출 0건, 순위→설명 변환 검증 | chat_analyzer.py + summarizer.py |
| B03 | 2026-04-17 | ✅ Tier2: bisect 슬라이싱 84x 속도향상 (5.07→0.06ms), edge case 통과 | summarizer.py |
| B04 | 2026-04-17 | ✅ Tier2: KeyError 크래시 확인 후 try/except 보호 | main.py |
| B05 | 2026-04-17 | ✅ Tier2: stall/overall timeout/pre-progress 3 시나리오 watchdog 검증 | transcriber.py + main.py + config.py |
| B06 | 2026-04-17 | ✅ Tier2: cleanup OSError 격리 + 잠긴 stale 파일 → 명시적 RuntimeError | downloader.py (3c2f518에서 bare pass 선제거, 잔여 cleanup 안정화) |
| B07 | 2026-04-17 | ✅ Tier2: known/unknown channel/global cfg 비변형 3 시나리오 검증 | main.py (streamers_by_channel 인덱스 + _build_streamer_cfg 헬퍼) |
| B08 | 2026-04-17 | ✅ Tier2: cues 공유 시 parse_srt 호출 0회, 미공유 fallback 1회 검증 | summarizer.py + subtitle_analyzer.py + community_matcher.py |
| B09 | 2026-04-17 | ✅ Tier2: strict/no-emoji/loose-bracket/total-fail 4 변형 + raw_fallback 항상 유지 | summarizer.py (_parse_summary_sections + _generate_html) |
| B10 | 2026-04-17 | ✅ Tier2: 첫 호출/TTL 내 재호출/TTL 만료/reset 4 시나리오 검증 (메인 방문 1→1→2→3) | scraper.py (_SESSION_CACHE + _get_or_create_session + reset_fmkorea_session) |
| B11 | 2026-04-17 | ✅ Tier2: recent/old/disabled/unparseable 4 시나리오 + naive datetime 처리 검증 | main.py (_vod_age_hours + _should_skip_fmkorea) + config.py (fmkorea_max_age_hours=48) |
| B12 | 2026-04-17 | ✅ Tier3: 1800s/10800s 클립 4×3 sweep, 3h 클립 radius=180/cold=60에서 70.4% 절감 + 98.3% 커버리지 추천 | experiments/b12_highlight_filter_sweep.py + results/2026-04-17_b12_*.{json,md} |
| B13 | 2026-04-17 | ✅ Tier3: 1800s/10800s × filter on/off × 4 chunk 후보 sweep, filter ON 기준 chunk_max_chars=15000 risk=low 추천 | experiments/b13_chunk_max_chars_sweep.py + results/2026-04-17_b13_*.{json,md} |
| B14 | 2026-04-17 | ✅ Tier3: `python -m pipeline.main --help` 한글 정상 출력 (cp949 콘솔에서도 깨짐 0건) | pipeline/main.py 진입부 sys.stdout/stderr UTF-8 reconfigure |
| B15 | 2026-04-17 | ✅ Tier3: 3개 entrypoint --help/compile 모두 한글 정상, B14 인라인 → DRY 헬퍼 교체 | pipeline/_io_encoding.py + main.py/transcribe.py/tray_app.py |
| B16 | 2026-04-17 | ✅ Tier1: grep 으로 nonexistent app.py/gui.py 참조 0건 확인, tray_app.py (실재) 만 잔존 | .prompts/00-autonomous-dev-loop.md (§3 step1, §5 재작성) |
| B17 | 2026-04-17 | ✅ Tier2: 4/4 happy+trailing RESOLUTION+빈 경로+미매칭 오프라인 검증 (requests.get monkeypatch) | content/network.py get_video_m3u8_base_url bound check + experiments/b17_m3u8_indexerror_guard.py |
| B18 | 2026-04-17 | ✅ Tier2: 5/5 FileNotFound race/Permission/OSError/which-missing baseline/TimeoutExpired passthrough | pipeline/claude_cli.py subprocess try-except + experiments/b18_claude_cli_oserror_guard.py |
| B19 | 2026-04-17 | ✅ Tier2: 8/8 ASCII 1쌍/2쌍/curly 1쌍/혼합/single+curly/빈/홀수 개+score 회귀 | pipeline/subtitle_analyzer.py _score_text quote 집계 수정 + experiments/b19_quote_count_typo.py |
| B20 | 2026-04-17 | ✅ Tier2: 7/7 happy/None/legacy/OSError/ValueError/멱등/실제TextIOWrapper | experiments/b20_io_encoding_tests.py (force_utf8_stdio 회귀 커버리지) |
| B21 | 2026-04-17 | ✅ Tier2: 13/13 default happy/claude_model 오타/문자열 수/음수/0 허용/None/enum 오타/cookies·list 타입/다중 aggregate/bool 거부/load_config 전파 | pipeline/config.py `ConfigError` + `validate_config()` + main.py 친절 종료 + experiments/b21_config_validation.py |
| B22 | 2026-04-17 | ✅ Tier2: 7/7 성공/실패 머지 × prompt leak/복구 가이드/helper 단독/traceback 숨김 | pipeline/summarizer.py `_format_failure_notice_for_llm` + `_build_failure_report` + experiments/b22_merge_failure_ux.py |
| B23 | 2026-04-17 | ✅ Tier2: 7/7 default None/커스텀 경로 반영/없는 경로 DEFAULT 생성/save/ConfigError 메시지 실제 경로/상대→절대 resolve/save·load 왕복 + B21 13/13 회귀 유지 | pipeline/config.py `_resolve_config_path` + `load_config(config_path=)` + `save_config(config_path=)` + `validate_config(source_path=)` + main.py `load_config(config_path=args.config)` + experiments/b23_config_path_arg.py |
| B24 | 2026-04-17 | ✅ Tier2: 7/7 ConfigError→exit2/에러 원문 전달/RuntimeError 전파/happy run()/비-win32 stderr/ctypes 실패 폴백/multi-line 메시지 + B23 7/7 + B21 13/13 회귀 유지 | tray_app.py `main()` ConfigError 포획 + `_show_fatal_dialog` Win32 MessageBoxW + experiments/b24_tray_config_error.py |
| B25 | 2026-04-17 | ✅ Tier2: 11/11 pid_alive 3종/lock 신규·stale·live·self·손상 5종/release 멱등/main 대화상자(exit 3)/B24 ConfigError exit 2 차별 회귀 + B24 7/7 + B23 7/7 + B21 13/13 회귀 유지 | tray_app.py `AlreadyRunningError` + `_pid_alive` + `_acquire_lock` + `_release_lock` + `_on_quit` 해제 + main() exit 3 + experiments/b25_tray_single_instance.py |
| B26 | 2026-04-25 | ✅ UA 로테이션(5종)/요청간격 8~12s/쿨다운 3h 마커/scraper_mode 설정 게이트/chromium 선택 시 NotImplementedError 명시 실패 | scraper.py USER_AGENTS + _is_in_cooldown + _mark_cooldown + scrape_fmkorea(work_dir, scraper_mode) + config.py fmkorea_scraper_mode + main.py 호출 갱신 |
| B27 | 2026-04-27 | ✅ Tier2: 6/6 dispatch chromium·http / invalid mode / 쿨다운 회귀 / playwright 미설치 폴백 / user_data_dir 레이아웃 + manual override 회귀 유지 (LIVE=1 옵션 검증 추가) | scraper.py `_scrape_fmkorea_http()` + `_scrape_fmkorea_chromium()` + `_playwright_user_data_dir()` + scrape_fmkorea() dispatch + requirements.txt playwright>=1.40 + experiments/b27_fmkorea_chromium.py + experiments/results/2026-04-27_b27_chromium-backend.md |
| B30 | 2026-04-27 | ✅ Tier2: 7/7 score 공식 / hot hour cap=6 / bin 내 점수 우선 / 3-bin 분산 / unknown bucket cap=25% / broadcast_dt 미제공 wall-clock fallback / 후보 < cap 시 전부 반환 + B27 6/6 + manual override 회귀 유지 | scraper.py `_score_post()` + `_select_top_diverse()` + scrape_fmkorea() 단순 슬라이스 교체 + experiments/b30_score_time_diversity.py + experiments/results/2026-04-27_b30_score-time-diversity.md |
| B31 | 2026-04-27 | ✅ Tier2: 9/9 HH:MM today/future-yesterday wrap / MM.DD 올해/작년 wrap / invalid date·time None / 기존 N분/시간/일 전·어제 HH:MM·YYYY.MM.DD HH:MM 회귀 + LIVE 검증 raw 400개 timestamp 파싱 0%→100% | scraper.py _parse_relative_time HH:MM 단독 + MM.DD 단독 + MM.DD HH:MM 미래 wrap + experiments/b31_timestamp_parser.py |
| B32 | 2026-04-27 | ✅ Tier2: 11/11 score formula / 경쟁 bin cap 보호 / 단일 bin 다중패스 fill / 점수 우선 / 3-bin 균등 / unknown cap pass1 / unknown overflow / wall-clock fallback / max>pool / **date-only day-bin 분류** / **day-bin cap이 hour-bin 보호** + LIVE 검증 95→120 달성, 누락 top score 4166→2066 (50% 개선) | scraper.py `_bin_key()` + `_select_top_diverse()` 다중 패스 (cap [base, 2x, ∞]) + `per_day_cap` 파라미터 + experiments/b30_score_time_diversity.py 11/11 + experiments/results/2026-04-27_b32_day-bin-multipass.md |
| — | — | — | — |
