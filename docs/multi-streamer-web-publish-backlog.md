# Multi-Streamer + Web Publish — Product Backlog

생성: 2026-04-16 (session `2026-04-16-multi-streamer-web-publish-mvp`, Turn 1)

이 문서는 Chzzk VOD 요약 파이프라인을 "멀티 스트리머 + 무료 웹 퍼블리시" 제품으로 확장하기 위한 실제 제품 백로그다. 한 세션 = 실제 산출 1개 원칙에 따라, 각 항목은 독립 세션 후보가 되도록 잘게 쪼개져 있다.

## Priority Table

| ID  | 항목                                   | 상태         |
|-----|----------------------------------------|--------------|
| P0  | 멀티 스트리머 publish 데이터 모델       | 완료 (runtime 구현) |
| P1  | 퍼블리시용 정적 사이트 스키마/빌더      | Slice 1 진행 |
| P2  | 웹 MVP UI (목록/상세/검색)              | Slice 1 진행 |
| P3  | 전문 검색 업그레이드 (N-gram/stemming) | 예정         |
| P4  | 자동 퍼블리시 (hook + 증분 rebuild)     | hook 구현 완료 (증분 미구현) |
| P5  | 무료 호스팅 배포 (Cloudflare Pages)     | scaffold + bundle CLI + self-host 완료 (실 계정 배포는 수동) |
| P6  | A4 cache-TTL 재측정 + chunk_max_tokens 승격 판단 | 보류        |
| P7  | 멀티 스트리머 설정 UI (tkinter)         | 완료 (add/edit/delete + legacy mirror) |

---

## P0 — 멀티 스트리머 publish 데이터 모델

- **목표:** 단일 스트리머(`target_channel_id` / `streamer_name`) 가정에 박혀 있는 파이프라인을 여러 스트리머를 운영 가능한 구조로 확장할 수 있는 **publish-view 데이터 모델**을 확정한다.
- **why now:** 현재 `pipeline_config.json`, `VODInfo.channel_name`, 메타데이터 JSON, `generate_reports()` 파일명, `PipelineState.processed_vods` 전부 플랫 구조다. 멀티 스트리머가 추가될 때 runtime 코드를 뜯지 않아도 publish 레이어에서 먼저 분리할 수 있어야 다음 슬라이스(사이트 빌더, 웹 UI)가 막히지 않는다.
- **예상 산출물:** `docs/publish-schema.md` (본 세션에서 작성), `publish/builder/schema.py` 데이터 클래스, 기존 output 메타에서 누락 필드를 **파생**하는 규칙.
- **난이도:** 낮음 (runtime 코드 변경 없이 publish-layer derivation 으로 우회).
- **Claude 토큰 소모 성격:** 없음. 코드/문서 작업.

## P1 — 퍼블리시용 정적 사이트 스키마/빌더

- **목표:** `output/` 의 기존 md/html/metadata 결과물을 읽어 `site/` 아래에 정적 호스팅 가능한 JSON + HTML 사본을 만드는 로컬 빌더를 구현한다.
- **why now:** 서버나 DB 없이도 무료 호스팅이 가능한 출발점. 파이프라인 런타임을 건드리지 않고 publish 레이어만으로 웹 제품이 성립한다.
- **예상 산출물:** `publish/builder/build_site.py`, 산출물 트리 `site/{index.json, streamers.json, streamers/<id>/index.json, vods/<video_no>/{index.json,report.html}, search-index.json, assets/}`.
- **난이도:** 중 (파일시스템 + JSON + 문자열 정제).
- **Claude 토큰 소모 성격:** 없음. 결정론적 파일 변환.

## P2 — 웹 MVP UI

- **목표:** 4화면 최소 UI — (1) 스트리머 목록 (2) 스트리머별 VOD 목록 (3) VOD 상세 요약 보기 (4) 검색.
- **why now:** 파이프라인 산출물이 "작동한다"는 것을 사람이 즉시 확인 가능하게 한다. 자동 퍼블리시/호스팅보다 먼저 풀-사이클을 닫는다.
- **예상 산출물:** `publish/web/` 아래 정적 `index.html`, `streamer.html`, `vod.html`, `search.html`, 공용 CSS/JS, 사이트 빌더가 `site/` 로 복사.
- **난이도:** 중 (프레임워크 없음. fetch + DOM 조립).
- **Claude 토큰 소모 성격:** 없음. 프론트엔드 정적 자산.

## P3 — 검색 업그레이드

- **목표:** 현재 Slice 1 검색은 `search-index.json` 에 대한 client-side substring 검색이다. 이를 KR 형태소/n-gram 기반으로 업그레이드한다.
- **why now:** Slice 1 의 substring 검색은 짧은 어휘(예: "올림픽")에 대해서는 작동하지만, 2~3어절 구문이나 조사 변형에는 약하다.
- **예상 산출물:** `publish/builder/search.py` (n-gram 인덱서), 결과 랭킹 스코어, `search.html` 하이라이트.
- **난이도:** 중-상.
- **Claude 토큰 소모 성격:** 없음.

## P4 — 자동 퍼블리시 hook

- **목표:** 파이프라인의 VOD 처리 완료 이벤트에서 site builder 를 자동 재실행. 또한 증분 빌드(변경된 VOD만 다시 기록) 지원.
- **why now:** Slice 1 은 "사용자가 수동으로 `python -m publish.builder.build_site` 를 돌리는" 상태다. 운영 자동화 단계.
- **예상 산출물:** `pipeline/main.py` 의 VOD 완료 후 hook, 혹은 `state.py` 의 `update(..., status="completed")` 에서 게시 트리거 옵션.
- **난이도:** 중 (runtime 코드 변경 최소화를 지켜야 함).
- **Claude 토큰 소모 성격:** 없음.

## P5 — 무료 호스팅 배포 (Cloudflare Pages 우선)

- **목표:** `site/` 디렉토리를 Cloudflare Pages 1순위, GitHub Pages 2순위로 정적 호스팅.
- **why now:** 본인 도메인/GPU 서버 없이 최소 비용으로 외부 노출을 시작하기 위함.
- **산출물 (scaffold 완료, 세션 `2026-04-16-free-hosting-deploy-scaffold`):**
  - `publish/web/{_redirects, _headers, .nojekyll}` + 빌더 (`build_site._copy_web_assets`)
    가 이 3개를 `site/` 로 emit.
  - `wrangler.toml` (Cloudflare CLI / Git-connected 모드 지원).
  - `.github/workflows/deploy-pages.yml` (manual `workflow_dispatch` only,
    `actions/upload-pages-artifact@v3` + `actions/deploy-pages@v4`, 쿠키 누출 grep 게이트
    포함).
  - `publish/deploy/check.py` — preflight CLI/library
    (구조/인덱스/쿠키/절대경로/CDN 검사, `--strict`, `--json`).
  - `experiments/deploy_scaffold_verify.py` — 8-test 검증 (build emit, preflight clean,
    cookie injection 감지, `--strict` 동작, TOML/YAML 파싱, 로컬 서빙, 실빌드 cookie scan).
  - `docs/deploy-free-hosting.md` 재작성 (scaffold 인지 표준 흐름).
- **추가 산출물 (세션 `2026-04-16-deploy-bundle-command-implement`):**
  - `publish/deploy/package.py` — bundle CLI/library
    (`--target {cloudflare,github-pages,all}`, `--strict`, `--rebuild`, `--clean`,
    `--json`). preflight 자동 실행 + errors 시 archive 미생성 + warnings + strict 시
    동일 차단. 산출물:
    `dist/deploy/{cloudflare/site-upload.zip, github-pages/site-artifact.tar.gz,
    manifest.json, checksums.txt}`. zip/tar 둘 다 publish 루트 layout, 결정적
    timestamp/uid/gid, gzip header timestamp 0 → 같은 site/ 입력에 byte-identical.
    archive 작성 후 cookie regex 재스캔 (defense in depth).
  - `experiments/deploy_package_verify.py` — 5-group 검증 (real bundles + 결정적
    layout, preflight cookie 게이트, `_headers` 제거 시 strict 차단, idempotent
    sha256, archive 내부 cookie 0건).
- **추가 산출물 (세션 `2026-04-17-self-host-report-assets-implement`):**
  - `publish/web/assets/vendor/chart.umd.min.js` — chart.js v4.4.2 vendored
    (sha256 `08dfa4730571b238...`, 205,488B). `pipeline/summarizer.py`
    template 이 `<script src="../../assets/vendor/chart.umd.min.js">` 를
    emit 하므로 newly-generated 리포트 HTML 은 외부 CDN 을 호출하지 않는다.
  - Google Fonts `@import` 제거. body/code 폰트는 시스템 fallback stack
    (`'Apple SD Gothic Neo', 'Malgun Gothic', '맑은 고딕', system-ui,
    -apple-system, 'Segoe UI'` / `'Cascadia Code', 'Fira Code', Consolas`).
  - `publish/builder/build_site._copy_web_assets` 가 `assets/vendor/` 를
    site/ 로 복사. 레거시 summarizer 가 만든 `output/<base>.html` 은
    `_rewrite_legacy_cdn_html` 가 빌드 시점에 CDN URL 을 local ref 로 치환.
  - `publish/deploy/check._check_external_cdn` 가 `assets/vendor/` 를
    스캔 대상에서 제외 (vendored payload 의 inert 문서 URL 은 runtime
    fetch 가 아님). 쿠키/절대경로 스캔은 그대로 적용.
  - `experiments/self_host_report_assets_verify.py` — 6-group 검증
    (report HTML CDN-free, vendor sha256 일치, `--strict` preflight pass,
    `--strict` package pass, http.server smoke, 쿠키 grep).
  - 결과: `python -m publish.deploy.check --site-dir ./site --strict` →
    exit 0, warnings 0; `python -m publish.deploy.package --target all
    --clean --strict` → exit 0, cloudflare zip + github-pages tar.gz 생성.
- **여전히 미수행:**
  - 실제 Cloudflare 계정 연동 / `wrangler pages deploy` 실행.
  - GH Pages 워크플로우의 실제 CI 실행 (manual-trigger 대기 상태).
  - bundle artifact 를 CI 산출물로 업로드 / release attach 자동화.
  - vendored chart.js 업데이트 정책 (현재는 수동 교체 + sha256 재계측).
  - 증분 빌드 + 자동 push 단계 (Slice-2 이후).
- **난이도:** 낮음 (정적 사이트 업로드 + scaffold).
- **Claude 토큰 소모 성격:** 없음.

## P7 — 멀티 스트리머 설정 UI (tkinter)

- **목표:** `pipeline/settings_ui.py` 의 단일-스트리머 스칼라 입력을 멀티 스트리머 행 편집기로 교체. 사용자가 GUI 에서 스트리머를 추가/수정/삭제할 수 있어야 한다.
- **why now:** runtime/publish 레이어는 이미 multi-streamer 를 지원하지만(`normalize_streamers()`), 사용자 진입점인 설정 GUI 는 여전히 단일 스트리머만 노출한다. 이 gap 이 사용성 측면의 가장 큰 잔여 격차였다.
- **산출물 (완료):**
  - `pipeline/settings_ui.py`: 스트리머 섹션이 동적 row 편집기로 변경. "+ 스트리머 추가" / 행별 "삭제" 버튼.
  - 저장 정책: `cfg["streamers"]` canonical list + 첫 행을 `target_channel_id` / `streamer_name` / `fmkorea_search_keywords` 로 mirror (downstream legacy 소비자 보호: tray_app, build_site fallback).
  - 입력 검증: 채널 ID 32자 hex 검사, 모두 빈 행 거부, 최소 1개 스트리머 강제.
  - 후방 호환: legacy single-streamer `pipeline_config.json` 은 1개 행으로 자동 표시.
- **검증 (`experiments/settings_ui_multi_streamer_verify.py`):**
  - T1 legacy_load (1행), T2 multi_load (3행), T3 save_policy (mirror), T4 roundtrip (JSON 직렬화), T5 empty fallback, T6 import smoke (FIELDS clean), T7 live Tk UI (load → add → delete → save → reload).
- **난이도:** 낮음 (UI 위젯 + 정책).
- **Claude 토큰 소모 성격:** 없음.

## P6 — A4 cache-TTL 재측정 + chunk_max_tokens 승격

- **목표:** 이전 A4 세션에서 deferred 된 W1/W2/W3 재측정을 cache-TTL-aware 프로토콜로 수행하고, 결과가 promotion gate를 통과하면 `chunk_max_tokens` 를 `DEFAULT_CONFIG` 에 승격.
- **why now:** 본 세션과 축이 다름. web publish MVP 작업이 runtime 정책에 의존하지 않도록 분리해둔다.
- **예상 산출물:** `experiments/results/{date}_phase-a4_retry.md`, promotion decision 기록.
- **난이도:** 상 (측정 반복성 + cache behavior).
- **Claude 토큰 소모 성격:** **높음** (Claude CLI 다수 호출, 재시도 포함).

---

## Slice 1 범위 요약

이번 세션이 닫는 것은 **P0 + P1 + P2 + P5의 문서화 부분**이다.
- P0: publish-view 스키마 정의 + 기존 output에서 파생 가능한 필드 규칙.
- P1: 결정론적 local builder.
- P2: 4화면 정적 웹 MVP.
- P5: Cloudflare Pages / GitHub Pages 배포 루트 문서화.

Slice 1 범위 **밖**인 것:
- P3 형태소/n-gram 검색 업그레이드.
- P4 runtime hook 전면 통합 (Slice 1 은 "수동 명령" + "next insertion point 문서화" 까지만).
- P5 실제 계정-연동 배포.
- P6 A4 재측정.
