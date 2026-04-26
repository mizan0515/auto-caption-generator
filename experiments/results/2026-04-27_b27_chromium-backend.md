# 2026-04-27 B27 fmkorea Chromium 백엔드

## 배경

`12925400` VOD 처리 중 fmkorea 검색 첫 요청에서 `HTTP 430` 즉시 차단 발생.
B26(UA 로테이션 + 8~12s 요청간격 + 3h 쿨다운) 만으로는 더 이상 안티봇 우회가
어려워졌고, requests 기반 TLS/JA3 fingerprint 가 Akamai bot manager 에 잡히는
정황. (직전 4/26 02:53 런은 80개 정상 수집 → IP 영구밴 아님, fingerprint 단계
차단으로 추정.)

## 결정

`fmkorea_scraper_mode="chromium"` 활성화 시 Playwright(headless Chromium) 로
검색 페이지를 렌더링/파싱하는 백엔드를 정식 구현. 기본값은 `"http"` 그대로
유지 — 사용자가 명시적으로 활성화해야 chromium 사용.

폴백 정책:
- playwright 미설치 → http 폴백 (warning)
- chromium 실행 실패 → http 폴백 (warning)
- 페이지 로드 중 429/430/CAPTCHA 감지 → `_mark_cooldown` 후 중단 (폴백 없음 — 차단된 IP 평판 회복 시간 확보)

## 구현

`pipeline/scraper.py`
- `_scrape_fmkorea_http(keywords, max_pages, work_dir)` — 기존 fetch 루프를 추출.
  raw post dict 리스트 반환.
- `_scrape_fmkorea_chromium(keywords, max_pages, work_dir)` — Playwright
  `launch_persistent_context(user_data_dir, headless, user_agent, locale, viewport)`
  로 1 컨텍스트 + 1 페이지 사용. `--disable-blink-features=AutomationControlled`
  로 navigator.webdriver 흔적 제거. 메인 페이지 1회 워밍 후 검색 페이지 순회.
  `page.content()` HTML 을 기존 `_parse_search_results()` 에 그대로 전달.
- `_playwright_user_data_dir(work_dir)` — 쿠키 persist 경로. work_dir 부모
  (즉 `./work/.playwright-userdata/`) 로 통일하여 VOD 간 쿠키/트러스트 공유.
- `scrape_fmkorea()` — NotImplementedError 자리에 dispatch 로 교체. 쿨다운/
  dedup/시간필터/CommunityPost 변환은 기존 그대로 상위에서 처리.

`requirements.txt`
- `playwright>=1.40.0  # optional` 추가. 설치 가이드 주석 동봉.

`pipeline/config.py`
- `fmkorea_scraper_mode` 기본값은 그대로 `"http"`. 사용자가 명시적으로
  `"chromium"` 으로 바꿔야 활성화.

## 검증

`python experiments/b27_fmkorea_chromium.py`
1. dispatch chromium → `_scrape_fmkorea_chromium` 호출 OK
2. dispatch http → `_scrape_fmkorea_http` 호출 OK (회귀)
3. invalid mode → ValueError 즉시
4. 쿨다운 마커 → 두 모드 모두 [] 반환, 백엔드 미호출 (회귀)
5. playwright 미설치 (ImportError 모킹) → http 폴백
6. user_data_dir 가 work_dir 부모 아래 .playwright-userdata 로 배치
7. (LIVE=1 옵션) 실제 fmkorea 1쿼리 ≥5개 파싱 — playwright install chromium 한 환경에서만 실행

`python experiments/test_manual_community_override.py` — 회귀 PASS (manual JSON
우선순위 유지).

## 운영 메모

- 활성화 절차:
  1. `pip install playwright`
  2. `playwright install chromium` (최초 1회, ~300MB 다운로드)
  3. `pipeline_config.json` 의 `fmkorea_scraper_mode` 를 `"chromium"` 으로 변경
- 부작용: 페이지당 3~5초 (http 대비 ~8배 느림). 키워드당 3페이지 기준 총 수집
  ~30~45초 증가. 전체 파이프라인 5h 대비 무시 가능.
- 쿠키 persist 디렉토리는 `./work/.playwright-userdata/` (work/ 가 이미
  .gitignore 되어 있어 자동 제외).
- chromium 도 결국 차단되면 manual JSON override 경로 (`*_community.manual.json`)
  로 우회. 4/25 메모 참조.
