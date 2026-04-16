# 무료 정적 호스팅 배포 가이드

최초 작성: 세션 `2026-04-16-multi-streamer-web-publish-mvp` Turn 1.
배포 scaffold 추가: 세션 `2026-04-16-free-hosting-deploy-scaffold` Turn 1.

본 문서는 `site/` 디렉토리(`publish/builder/build_site.py` 산출물)를 무료 정적 호스팅
서비스에 올리는 방법을 정리한다. 이번 scaffold 세션에서도 **실 계정 연동 배포까지는
강제하지 않는다.** "어떤 폴더/파일/워크플로우가 배포 루트와 컨트롤 플레인을 구성하는지"가
명확하고 로컬에서 재현 가능한 검증이 되어 있는 것이 완료 조건이다.

## 배포 루트

- **배포 루트:** `site/` (리포지토리 루트 기준 `./site`).
- **엔트리 포인트:** `site/index.html`.
- **빌드 산출물에 포함되는 deploy meta:**
  - `site/_redirects` — Cloudflare Pages 용 404 fallback.
  - `site/_headers` — Cloudflare Pages 용 캐시/보안 헤더 (`/assets/*` 1일, HTML/JSON 5분,
    `X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`,
    `Referrer-Policy: strict-origin-when-cross-origin`).
  - `site/.nojekyll` — GitHub Pages 에서 underscore-prefixed 파일(`_redirects`, `_headers`)
    이 Jekyll 에 의해 필터링되지 않게 한다.
- **요구 없음:** 빌드 스크립트 / 서버 실행 / 쿠키 / 환경 변수.
- **주의:** `pipeline_config.json`, `output/`, `work/`, `Document/` 는 배포 루트에 포함되지
  않는다. `site/` 만 올리면 된다.

### 왜 `X-Frame-Options: SAMEORIGIN` 인가

`site/vod.html` 이 같은 오리진의 `vods/<video_no>/report.html` 을 iframe 으로 embed 한다.
`DENY` 로 하면 VOD 상세 화면 본문이 로드되지 않는다. `SAMEORIGIN` 이 최소 허용 값이다.

## 빌드 → 검증 → 배포 (표준 흐름)

```bash
# 1. 빌드: output/ → site/ (deploy meta 포함)
python -m publish.builder.build_site

# 2. preflight 검증: 구조 + 쿠키 누출 + 절대경로 + 외부 CDN 의존
python -m publish.deploy.check --site-dir ./site
#    --strict  경고를 실패로 승격 (CI 에서 사용)
#    --json    기계 판독 가능한 JSON 결과

# 3. 로컬 시각 확인
python -m http.server --directory site 8000
# 브라우저: http://localhost:8000/

# 4. 업로드 bundle 생성 (preflight 자동 실행, 실패 시 패키지 거부)
python -m publish.deploy.package --target all
#    --target {cloudflare,github-pages,all}  (기본 all, 반복 가능)
#    --strict                                  preflight 경고도 차단 사유로 승격
#    --rebuild                                 패키징 직전에 build_site 재실행
#    --clean                                   기존 --out-dir 를 비우고 작성
#    --json                                    결과 JSON 출력
# 산출물:
#    dist/deploy/cloudflare/site-upload.zip          (Direct Upload 호환)
#    dist/deploy/github-pages/site-artifact.tar.gz   (upload-pages-artifact 호환)
#    dist/deploy/manifest.json                       (preflight info + 번들 메타)
#    dist/deploy/checksums.txt                       (sha256, 한 번들당 한 줄)
# 같은 site/ 입력 → byte-identical archive (sha256 동일).

# 5. 배포 (아래 옵션 A 또는 B 선택)
```

preflight 검증 항목:

- 필수 HTML: `index.html`, `streamer.html`, `vod.html`, `search.html`.
- 필수 JSON: `index.json`, `streamers.json`, `search-index.json`.
- 필수 asset: `assets/app.css`, `assets/app.js`.
- deploy meta (경고): `_redirects`, `_headers`, `.nojekyll`.
- 인덱스 카운트: `index.json.total_streamers >= 1`, `total_vods >= 1`.
- **쿠키 누출 스캔: `NID_AUT` / `NID_SES` 가 포함된 모든 텍스트 파일 거부.**
- 절대 경로 누출 (`C:\Users\...`, `/home/<user>/...`).
- 외부 CDN 의존 (경고 only). 본 저장소는 chart.js 를 `assets/vendor/` 에 self-host
  하고 폰트는 시스템 fallback stack 으로 처리하므로 baseline 은 `--strict`
  통과 (외부 URL 경고 0). `assets/vendor/` 내부 파일은 vendored third-party
  payload 의 inert 문서 URL (chartjs.org, jsdelivr docs 등) 을 포함하므로
  CDN 스캔에서 제외된다 — 쿠키/절대경로 스캔은 그대로 적용된다.

## 옵션 A — Cloudflare Pages (권장, 1순위)

### A1. Direct Upload (계정만 있으면 즉시 작동)

1. Cloudflare 계정 → Pages → Create project → **Upload assets** 선택.
2. Project name 임의. Production branch/build command 는 **비워둔다**.
3. `site/` 폴더 전체 drag-and-drop, 또는 `dist/deploy/cloudflare/site-upload.zip`
   업로드 (zip 내부가 publish 루트에 그대로 풀린다).
4. `<프로젝트이름>.pages.dev` 서브도메인이 즉시 부여.
5. `site/_redirects` 와 `site/_headers` 는 Cloudflare 가 자동 인식.

### A2. Wrangler CLI

리포지토리 루트에 `wrangler.toml` 이 포함되어 있다:

```toml
name = "auto-caption-generator-site"
compatibility_date = "2024-12-01"
pages_build_output_dir = "./site"
```

로컬 로그인 후 한 명령으로 배포:

```bash
npx wrangler login
npx wrangler pages deploy site
```

### 왜 1순위인가

- **월 500 빌드 + 무제한 요청.** 개인 퍼블리시 수준에서는 사실상 무료.
- 전 세계 CDN + HTTPS 자동. 한국 리전도 빠르다.
- Git 연동 없이 Direct Upload / CLI 로 배포 가능 → `pipeline_config.json` 이 gitignored 인
  현 구조와 충돌 없음.
- `_redirects` / `_headers` native 지원 → Slice-2 에서 SPA 라우팅이나 캐시 정책 튜닝이
  필요해져도 본 저장소 자원만으로 대응 가능.

## 옵션 B — GitHub Pages (fallback)

`.github/workflows/deploy-pages.yml` 가 manual-trigger 전용 scaffold 로 포함됨:

- `on: workflow_dispatch` — push/PR 자동 실행 금지. `Actions` 탭에서 `Run workflow` 로만
  실행된다. 의도치 않은 배포 방지 목적.
- 권한: `contents: read`, `pages: write`, `id-token: write` (GitHub Pages 최소 요건).
- 핵심 단계:
  1. `actions/checkout@v4`
  2. `site/index.html` 존재 확인 (없으면 에러로 즉시 중단)
  3. `site/.nojekyll` 없을 때만 `touch` (빌더가 이미 emit 하지만 defensive)
  4. **`grep -RIl 'NID_AUT|NID_SES' site/` — hit 있으면 에러로 중단 (쿠키 누출 게이트)**
  5. `actions/configure-pages@v5`
  6. `actions/upload-pages-artifact@v3` (path: `./site`)
  7. `actions/deploy-pages@v4`

### GH Pages 사용 시 주의

본 저장소는 기본적으로 `site/` 가 `.gitignore` 로 제외된다. GH Pages 는 `git clone` 만으로
`site/` 가 워크스페이스에 존재해야 작동하므로, 다음 중 하나를 택해야 한다:

- (A) 별도 publish 브랜치(예: `gh-pages-data`)에 빌드 결과를 commit 하고 그 브랜치에서
  workflow 를 실행.
- (B) fork 해서 `.gitignore` 의 `site/` 제외 규칙을 풀고 `main` 에 commit.
- (C) 다른 빌드 워크플로우가 `actions/upload-artifact` 로 올린 `site` 를 이 워크플로우 앞에
  `actions/download-artifact` 로 받는 단계를 추가.

(구현 경로는 사용자 환경에 의존한다. 본 scaffold 는 (A)/(B) 를 기본 가정한다.)

### 개인정보/쿠키 주의

public repo 에 실제 데이터를 push 하기 전 다음을 반드시 확인:

- `pipeline_config.json`, `output/`, `work/` 는 이미 `.gitignore` 에 포함.
- `site/` 내부의 md/html 요약물 자체가 방송 내용을 반영한다는 점.
- `python -m publish.deploy.check --site-dir ./site` 가 clean 하게 끝나는지 (쿠키 누출 0건).

## 옵션 C — 다른 대안들

- **Netlify**: Cloudflare Pages 와 거의 동일한 기능 매트릭스. `_redirects`/`_headers` 를 같은
  형식으로 인식. 다만 무료 플랜 bandwidth 제한이 타이트.
- **Vercel**: 정적 사이트는 무료 플랜에서 동작. 단, 개인 non-commercial 제약 있음.
- **S3 + CloudFront**: 월 $1 미만. 본 규모에서는 오버킬.

## 자동 퍼블리시 (현 상태)

- VOD 처리 성공 시 `publish.hook` 이 `build_site` 를 자동 호출 (기본 ON, backlog `P4` 완료).
- 본 세션의 scaffold 는 **hook → site/ 재빌드** 까지만 자동이다. 재빌드된 `site/` 를 실제
  호스팅으로 밀어넣는 단계는 여전히 사용자 수동 트리거 (Direct Upload / Wrangler CLI /
  GH Pages manual workflow).
- 증분 빌드 및 `wrangler pages deploy site --commit-dirty=true` 자동화는 Slice-2 이후.

## 배포 전 체크리스트 (표준)

- [ ] `python -m publish.builder.build_site` 가 에러 없이 종료.
- [ ] `site/index.json.total_vods > 0` (빈 사이트 거부).
- [ ] `site/{index,streamer,vod,search}.html` 4개 존재.
- [ ] `site/_redirects`, `site/_headers`, `site/.nojekyll` 3개 존재.
- [ ] `python -m publish.deploy.check --site-dir ./site` → `ERRORS` 0건.
- [ ] (CI 에 태울 경우) `python -m publish.deploy.check --strict` → exit 0.
- [ ] `python -m publish.deploy.package --target all` → `OK - deploy bundles ready.`
      (preflight 자동 실행, errors 시 archive 미생성).
- [ ] `dist/deploy/{cloudflare/site-upload.zip, github-pages/site-artifact.tar.gz,
      manifest.json, checksums.txt}` 4개 산출물 존재.
- [ ] `site/vods/<video_no>/report.html` 을 브라우저에서 열어 기존 리포트와 동일하게 렌더링.
- [ ] (업로드 전) 방송 내용 public 공개 여부에 대한 본인 판단 재확인.

## 재현 가능한 검증 스크립트

`experiments/deploy_scaffold_verify.py` 가 본 scaffold 의 8-test 검증을 한 번에 돌린다:

```bash
PYTHONIOENCODING=utf-8 python experiments/deploy_scaffold_verify.py
```

테스트 대상:

- T1 build → deploy meta 3종 emit.
- T2 preflight clean 통과 + 인덱스 카운트.
- T3 `NID_AUT` 주입 감지 (쿠키 누출 게이트 적극 증명).
- T4 `_headers` 제거 → 경고 + `--strict` 시 exit 2.
- T5 `wrangler.toml` TOML 파싱 + 필수 키.
- T6 `deploy-pages.yml` YAML 파싱 + manual-only + 필수 action 참조.
- T7 `python -m http.server` 로 `/index.html` + `/index.json` 200.
- T8 실빌드 결과물에 `NID_AUT/NID_SES` 0건 (defense in depth).

`experiments/deploy_package_verify.py` 는 bundle command 의 5-group 검증을 돌린다:

```bash
PYTHONIOENCODING=utf-8 python experiments/deploy_package_verify.py
```

테스트 대상:

- T1+T2+T3 real bundles + zip/tar 모두 publish 루트 layout, 결정적 timestamp,
  manifest.json + checksums.txt 정상.
- T4 `NID_AUT` 주입 → preflight 게이트 차단, archive 파일 미생성.
- T5 `_headers` 제거 → non-strict 통과, `--strict` 차단 (archive 미생성).
- T6 동일 입력 두 번 패키징 → 양 타겟 sha256 일치 (idempotent).
- T7 양쪽 archive 의 모든 entry 에서 `NID_AUT/NID_SES` 0건.

`experiments/self_host_report_assets_verify.py` 는 per-VOD report HTML 의
외부 CDN 제거 슬라이스 검증 6-group 을 돌린다:

```bash
PYTHONIOENCODING=utf-8 python experiments/self_host_report_assets_verify.py
```

테스트 대상:

- T1 `site/vods/<id>/report.html` 에 외부 `https://` 참조 0, local
  `../../assets/vendor/chart.umd.min.js` 참조 존재.
- T2 `site/assets/vendor/chart.umd.min.js` 가 source (`publish/web/assets/vendor/`)
  와 sha256 일치.
- T3 `publish.deploy.check --site-dir ./site --strict` → exit 0 (경고 0).
- T4 `publish.deploy.package --target all --clean --strict` → exit 0,
  cloudflare zip + github-pages tar.gz 모두 생성.
- T5 tempdir 로 복사한 `site/` 를 `http.server` 로 serve → `/index.html`,
  `/vod.html`, `/vods/<id>/report.html`, `/assets/vendor/chart.umd.min.js`
  네 엔드포인트가 모두 200.
- T6 `NID_AUT/NID_SES` 가 site 전체에 0건.
