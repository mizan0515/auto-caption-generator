# Chzzk VOD 자동 모니터링 & 요약 파이프라인

Chzzk 스트리머의 다시보기(VOD)를 자동 감지하여 다운로드 > 자막 생성 > 채팅 분석 > 커뮤니티 수집 > AI 요약 리포트까지 전 과정을 자동화하는 파이프라인.

---

## 파이프라인 흐름

```
새 VOD 감지 → 144p 다운로드 → Whisper 자막 생성 → 채팅 하이라이트 분석
                                                          ↓
      fmkorea 커뮤니티 수집 ────────────────────→ Claude AI 통합 요약
                                                          ↓
                                              Markdown + HTML 리포트
```

### 처리 단계

| 단계 | 설명 |
|------|------|
| 1. 모니터링 | Chzzk API를 주기적으로 폴링하여 새 VOD 감지 |
| 2. 데이터 수집 | VOD 다운로드 + 채팅 수집 + 커뮤니티 스크래핑 (병렬) |
| 3. 분석 | 채팅 밀도 + 감정 키워드 기반 하이라이트 구간 탐지 |
| 4. 자막 생성 | Whisper large-v3-turbo + Silero VAD 로 한국어 자막(SRT) 생성 |
| 5. AI 요약 | SRT를 청크로 분할 후 Claude CLI로 구간별 분석 → 통합 리포트 |
| 6. 출력 | Markdown + HTML 리포트 + 메타데이터 JSON 저장 |

---

## 원클릭 시작 (권장)

Python 3.10+ 만 있으면:

```bash
start.bat
```

`scripts/first_run.py` 가 실행되어:
1. Python / pip 의존성 / ffmpeg / claude CLI / wrangler 자동 점검
2. 누락된 pip 패키지 자동 설치, 외부 도구는 설치 명령 안내
3. `pipeline_config.json` 부재/쿠키 부재 시 설정 GUI 자동 호출
4. 모든 점검 통과 시 트레이 앱 detached 실행

이후엔 `start.bat` 더블클릭만으로 2초 안에 트레이 기동 (이미 구성된 경우).

단독 점검만 하려면:
```bash
python scripts/first_run.py --check
```

---

## 설치 (수동)

### 사전 요구사항

- **Python 3.10+**
- **ffmpeg** (PATH에 등록)
- **Claude Code CLI** (`claude` 명령어가 PATH에 등록)
- **CUDA 지원 GPU** (권장, Whisper 가속)

### 의존성 설치

```bash
pip install -r requirements.txt
```

### ffmpeg 설치 (Windows)

```bash
winget install Gyan.FFmpeg
```

---

## 설정

### 방법 1: 설정 GUI (권장)

```bash
python -m pipeline.settings_ui
```

스트리머, 검색 키워드, 쿠키 등을 GUI에서 편집할 수 있습니다.
**멀티 스트리머** 를 지원하며, 상단 "스트리머" 섹션에서 여러 채널을 동시에 추가/수정/삭제할 수 있습니다. 첫 번째 스트리머는 legacy 단일-스트리머 필드(`target_channel_id`, `streamer_name`)로도 자동 동기화되어 기존 운영과 호환됩니다.

### 방법 2: 설정 파일 직접 편집

첫 실행 시 `pipeline_config.json`이 자동 생성됩니다.

```jsonc
{
  "target_channel_id": "a7e175625fdea5a7d98428302b7aa57f",  // 채널 ID (32자리, legacy 단일 모드)
  "streamer_name": "탬탬",                                    // 표시용 이름
  "poll_interval_sec": 300,                                   // 폴링 간격 (초)
  "download_resolution": 144,                                 // 다운로드 해상도
  "whisper_vad_prescan_workers": 4,                           // 기본 4(per-thread VAD, ~3x 가속). 크래시 재발 시 1 로 하향
  "fmkorea_enabled": true,                                    // 커뮤니티 수집 on/off
  "fmkorea_search_keywords": ["탬탬버린", "탬탬"],             // 검색 키워드
  "cookies": {
    "NID_AUT": "",                                            // Chzzk 쿠키
    "NID_SES": ""
  }
}
```

#### 멀티 스트리머 (canonical form)

여러 스트리머를 동시에 모니터링하려면 `streamers` 리스트를 사용합니다.
설정 GUI 의 "스트리머" 섹션이 이 형식을 그대로 읽고/씁니다.

```jsonc
{
  "streamers": [
    {
      "channel_id": "a7e175625fdea5a7d98428302b7aa57f",
      "name": "탬탬",
      "search_keywords": ["탬탬버린", "탬탬"]
    },
    {
      "channel_id": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      "name": "스트리머B",
      "search_keywords": ["B키워드"]
    }
  ],
  // 첫 스트리머는 legacy 호환을 위해 아래에도 자동 mirror 됩니다 (GUI 저장 시):
  "target_channel_id": "a7e175625fdea5a7d98428302b7aa57f",
  "streamer_name": "탬탬",
  "fmkorea_search_keywords": ["탬탬버린", "탬탬"],

  "poll_interval_sec": 300,
  "cookies": { "NID_AUT": "", "NID_SES": "" }
}
```

`streamers` 가 비어 있거나 없으면 legacy `target_channel_id` / `streamer_name` 만으로
한 명의 스트리머를 처리하는 단일 모드로 동작합니다 (`pipeline.config.normalize_streamers()` 가
양쪽 형식을 모두 정규화합니다).

### 방법 3: CLI 쿠키 설정

```bash
python -m pipeline.main --setup-cookies
```

### 쿠키 발급 방법

1. 크롬에서 [chzzk.naver.com](https://chzzk.naver.com) 로그인
2. `F12` > `Application` > `Cookies` > `chzzk.naver.com`
3. `NID_AUT`, `NID_SES` 값을 복사
4. 설정 GUI 또는 `pipeline_config.json`에 붙여넣기

### VAD 크래시 대응

`whisper_vad_prescan_workers` 기본값은 `4` (per-thread VAD 모델 인스턴스 방식).
각 워커가 `threading.local()` 을 통해 자기 Silero VAD 인스턴스를 갖도록 지연
로딩하므로, 과거에 관측된 공유-모델 heap corruption (0xc0000374) 은 구조적으로
제거됩니다. 검증 실험: `experiments/test_vad_prescan_threadlocal.py` — 4 part
기준 workers=4 에서 x3.13 가속, segments 완전 일치.

Windows에서 `pythonw.exe - 응용 프로그램 오류`와 함께 `메모리를 read될 수 없습니다`가
뜨면서 Whisper 단계가 죽으면:

- 즉시 `whisper_vad_prescan_workers` 를 `1` 로 낮추세요.
- `experiments/results/` 에 환경(torch/silero 버전)과 로그를 남기세요.
- `VAD 사전 분석 중` 직후 크래시 이력이 있는 머신이라면 `1` 에서 올리지 않는 것이
  안전합니다.

### fmkorea 430 대응

fmkorea가 `HTTP 430 (rate limit/anti-bot)`를 반환하면 자동 스크랩은 즉시 중단됩니다.
이건 현재 코드도 의도적으로 재시도하지 않습니다. 같은 fingerprint로 계속 때리면 더 나빠지기 때문입니다.

대신 수동 override를 넣을 수 있습니다.

1. 브라우저에서 직접 관련 글을 찾습니다.
2. 아래 경로에 JSON 파일을 만듭니다.

```text
work/<video_no>/<video_no>_community.manual.json
```

예:

```json
[
  {
    "title": "탬탬 호종컵 고수달 관련 반응",
    "url": "https://www.fmkorea.com/1234567890",
    "body_preview": "오물달 밈 얘기가 많았음",
    "author": "닉네임",
    "timestamp": "2026.04.25 02:03",
    "views": 1234,
    "comments": 45,
    "likes": 18
  }
]
```

3. 같은 VOD를 다시 처리하면, 파이프라인은 이 파일을 먼저 읽고 `fmkorea` 스크랩을 건너뜁니다.

로그는 이렇게 바뀝니다.

```text
✓ 수동 커뮤니티 입력 재사용: N개 (fmkorea 스크랩 스킵)
```

---

## 실행

### 시스템 트레이 (권장)

```bash
pythonw tray_app.py
```

또는 `pipeline_tray.bat`를 더블클릭합니다.

Windows 시스템 트레이에 아이콘이 나타나며, 우클릭 메뉴:

| 메뉴 | 설명 |
|------|------|
| **상태 확인** | 현재 처리 중인 VOD 정보 표시 |
| **설정** | 설정 GUI 열기 |
| **로그 열기** | 로그 파일을 텍스트 에디터로 열기 |
| **출력 폴더 열기** | 리포트가 저장된 폴더 열기 |
| **설정 파일 직접 편집** | pipeline_config.json 열기 |
| **일시정지 / 재개** | 모니터링 일시정지/재개 |
| **종료** | 파이프라인 중지 후 트레이 종료 |

### CLI 모드

```bash
# 데몬 모드 (백그라운드 상시 모니터링)
python -m pipeline.main

# 1회 실행 (새 VOD 확인 후 종료)
python -m pipeline.main --once

# 특정 VOD 수동 처리
python -m pipeline.main --process 12345678
```

### 배치 파일

```bash
# 트레이 앱 실행
pipeline_tray.bat

# CLI 데몬 실행
pipeline_daemon.bat
```

---

## 출력 구조

```
output/
  ├── logs/
  │   └── pipeline.log              # 로테이팅 로그 (10MB x 5)
  ├── pipeline_state.json           # 처리 상태 추적
  ├── 스트리머_방송제목.md           # Markdown 리포트
  ├── 스트리머_방송제목.html         # HTML 리포트 (브라우저로 열기)
  └── 스트리머_방송제목_metadata.json # 메타데이터
```

---

## 웹 퍼블리시 (멀티 스트리머 MVP)

`output/` 의 리포트를 정적 사이트로 묶어 무료 호스팅에 올릴 수 있다.
자세한 스키마·백로그·배포 경로는 다음 문서 참조:

- [`docs/multi-streamer-web-publish-backlog.md`](docs/multi-streamer-web-publish-backlog.md) — 제품 백로그(P0~P6).
- [`docs/publish-schema.md`](docs/publish-schema.md) — publish-view 스키마와 파생 규칙.
- [`docs/deploy-free-hosting.md`](docs/deploy-free-hosting.md) — Cloudflare Pages(1순위) / GitHub Pages.
- [`docs/auto-publish-hook-plan.md`](docs/auto-publish-hook-plan.md) — 자동 퍼블리시 훅 구현 상태.

### 자동 퍼블리시

VOD 처리가 성공하면 `site/` 가 자동으로 재빌드된다 (기본 활성).
비활성화: `pipeline_config.json` 에서 `"publish_autorebuild": false`.

### 빌드 (수동)

```bash
# output/ 을 읽어 site/ 정적 트리를 생성
python -m publish.builder.build_site

# 또는 예외를 흡수하는 얕은 훅 래퍼로 호출
python -m publish.hook
```

생성되는 트리 개요:

```
site/
├── index.html        streamer.html  vod.html  search.html
├── assets/app.{css,js}
├── index.json        streamers.json              # 전역 목록
├── streamers/<streamer_id>/index.json            # 스트리머별 VOD 목록
├── vods/<video_no>/{index.json, report.html, report.md, metadata.json}
└── search-index.json                             # 클라이언트-사이드 검색용
```

### 로컬 확인

```bash
python -m http.server --directory site 8000
# 브라우저에서 http://localhost:8000/ 접속
```

### 관리자 전용 리포트 편집 페이지

공개 `site/vods/<video_no>/report.html` 은 그대로 읽기 전용으로 배포하고,
관리자 수정은 로컬 전용 편집 페이지에서만 한다.

```bash
# 기본: http://127.0.0.1:8766/
python scripts/report_admin_server.py

# 또는 Windows 배치 파일
report_admin.bat
```

- 기본 바인딩은 `127.0.0.1` 이라 외부에서 직접 접근할 수 없다.
- `/` 는 전체 리포트 목록과 검색 화면이고, 항목을 클릭하면 `/report?base=...` 편집 화면으로 이동한다.
- 목록은 `output/` 리포트와 `site/vods/` 에만 남아 있는 기존 리포트를 함께 보여준다 (`site-only` 표시).
- 편집 화면에서 원본 요약 마크다운을 수정하면 미리보기와 저장을 할 수 있다.
- `저장 후 site 재퍼블리시` 를 켜 두면 `output/*.md`, `output/*.html`, `site/` 가 한 번에 갱신된다.
- 네이버 카페 붙여넣기 HTML 과 치지직 다시보기 댓글 붙여넣기용 텍스트도 같은 원본 마크다운에서 다시 생성되므로 별도 수동 수정이 필요 없다.
- 편집 화면의 `유튜브 다시보기 댓글 붙여넣기용` 섹션에서 YouTube URL 을 넣으면, 기존 치지직 요약 타임라인을 유튜브 시간축 기준으로 재매핑한 댓글용 텍스트를 만들 수 있다.
- 포트 변경이 필요하면 `python scripts/report_admin_server.py --port 8877` 처럼 실행한다.

#### 유튜브 다시보기 정렬 사용법

유튜브 다시보기는 치지직 VOD 와 시작 시점, 길이, 중간 컷 편집이 다를 수 있다.
그래서 이 기능은 `완전 자동`이 아니라 `자동 초안 + 수동 보정` 흐름으로 설계되어 있다.

1. 관리자 편집 화면에서 해당 VOD 를 연다.
2. `유튜브 다시보기 댓글 붙여넣기용` 섹션에 YouTube URL 을 넣고 `유튜브 미리보기 생성` 을 누른다.
3. 시스템이 치지직 길이와 유튜브 길이 차이로 자동 offset 을 계산해 초안 타임라인을 만든다.
4. 추천 앵커 4개 중 실제로 찾기 쉬운 장면 2개 이상을 유튜브에서 확인하고, 해당 유튜브 시각을 입력한다.
5. 다시 `유튜브 미리보기 생성` 을 누르면 입력한 앵커 기준으로 offset 또는 piecewise 보정이 적용된다.
6. 결과가 맞으면 `텍스트 복사` 로 댓글용 텍스트를 가져가거나 `정렬 설정 저장` 으로 `youtube_alignment.json` 을 저장한다.

권장 앵커 선택 기준:

- 제목에 `픽`, `확정`, `승리`, `탄생`, `개막`, `커버` 같은 단어가 있는 장면을 우선 사용한다.
- 가능한 한 방송 전반에 걸쳐 떨어진 시점 2개 이상을 고른다.
- 두 앵커가 비슷한 오프셋이면 단순 시작 지연 케이스다.
- 앵커별 오프셋이 다르면 중간 컷 편집이 있는 영상일 가능성이 높다.

출력 하단에 표시되는 `confidence` 해석:

- `0.45` 전후: 길이차만 사용한 자동 초안
- `0.72` 전후: 수동 앵커 1개로 보정
- `0.86` 전후: 수동 앵커 2개 이상이 거의 같은 offset 에 합의
- `0.78~0.90`: 구간별 piecewise 보정

제한 사항:

- YouTube URL 이 비공개, 연령 제한, 지역 제한이면 메타데이터 읽기가 실패할 수 있다.
- 자막 기반 요약을 유튜브 시간축으로 옮기는 방식이라 몇 초 정도 오차는 남을 수 있다.
- 앵커를 2개 이상 넣으면 정확도가 크게 올라간다. 길이차만으로는 중간 컷 편집을 복원할 수 없다.

### 배포

빌드된 `site/` 디렉토리를 무료 정적 호스팅에 올린다. 빌더가 deploy meta
파일(`_redirects`, `_headers`, `.nojekyll`) 을 함께 emit 하므로 추가 설정 없이
Cloudflare Pages / GitHub Pages 양쪽으로 같은 `site/` 트리를 그대로 쓴다.
리포트 HTML 의 chart.js 와 폰트는 `assets/vendor/` 에 self-host 되므로
`--strict` 가 경고 0 으로 통과한다 (외부 CDN 의존 없음).

```bash
# 1. 빌드 (output/ → site/)
python -m publish.builder.build_site

# 2. 배포 전 preflight 검증 (구조 + 쿠키 누출 + 외부 CDN 스캔)
python -m publish.deploy.check --site-dir ./site --strict
#   --strict: 경고를 실패로 승격 (CI 용; 본 저장소는 strict 통과 baseline)
#   --json:   기계 판독용 JSON 출력

# 3. 업로드용 deploy bundle 생성 (preflight 자동 실행, 실패 시 패키지 미생성)
python -m publish.deploy.package --target all --strict
#   --target cloudflare    : dist/deploy/cloudflare/site-upload.zip 만 생성
#   --target github-pages  : dist/deploy/github-pages/site-artifact.tar.gz 만 생성
#   --target all           : 두 타겟 모두 (기본)
#   --strict               : preflight 경고도 차단 사유로 승격
#   --rebuild              : 패키징 전에 build_site 를 다시 돌림
#   --clean                : 기존 --out-dir 를 지우고 다시 작성
#   --json                 : 결과를 JSON 으로 출력
# 산출물: dist/deploy/{cloudflare/site-upload.zip, github-pages/site-artifact.tar.gz,
#         manifest.json, checksums.txt}. 같은 site/ 입력에 대해 byte-identical.
```

옵션 A — **Cloudflare Pages** (권장, 1순위)

- Direct Upload: `site/` 폴더를 dashboard 에 drag-and-drop.
- Direct Upload (zip): `dist/deploy/cloudflare/site-upload.zip` 을 dashboard 에 업로드.
- Wrangler CLI: `wrangler pages deploy site` (`wrangler.toml` 이 repo 루트에 포함됨).

옵션 B — **GitHub Pages** (fallback)

- `.github/workflows/deploy-pages.yml` 가 manual-trigger 전용 scaffold 로 포함됨.
- `Actions` 탭 → `Deploy site to GitHub Pages` → `Run workflow`.
- 사전 조건: workflow checkout 시점에 `site/` 가 ref 상에 존재해야 한다.
  본 저장소는 `site/` 가 gitignored 이므로, 별도 publish 브랜치에 commit
  하거나 `.gitignore` 의 site 제외를 풀어야 한다 (워크플로우 헤더 주석 참조).

자세한 옵션·체크리스트·왜 Cloudflare 가 1순위인지: [`docs/deploy-free-hosting.md`](docs/deploy-free-hosting.md).

---

## 운용 가이드

### 종료 방법

- **트레이 모드**: 트레이 아이콘 우클릭 > 종료
- **CLI 모드**: `Ctrl+C` 또는 `output/pipeline_state.json`에서 `"stop": true`로 변경

### 일시정지 / 재개

- **트레이 모드**: 트레이 아이콘 우클릭 > 일시정지 / 재개
- **CLI 모드**: `pipeline_state.json`의 `"stop"` 필드를 `true`/`false`로 토글

### 실패 VOD 재처리

실패한 VOD는 자동으로 최대 3회까지 재시도됩니다.
수동 재처리:

```bash
python -m pipeline.main --process <VOD번호>
```

### 설정 변경 반영

트레이 모드에서 설정을 변경하면 **다음 폴링 주기**부터 자동 반영됩니다.
CLI 데몬 모드는 재시작이 필요합니다.

### 로그 확인

```bash
# 실시간 로그 확인 (PowerShell)
Get-Content output/logs/pipeline.log -Wait -Tail 50
```

---

## DAD 운영 원칙

이 저장소는 Codex/Claude Code 협업용 DAD(Dual-Agent Dialogue) 문서를 포함하지만,
운영 원칙은 **문서 관리보다 제품 진전 우선**입니다.

- DAD는 측정, 버그 수정, smoke, 설정 판단처럼 실제 사용성에 직결되는 작업에 우선 사용합니다.
- 기본 단위는 **한 세션 = 실제 산출 1개**입니다.
- 다음은 지양합니다:
  - peer-verify only 세션
  - wording correction only 세션
  - closure seal only 세션
  - state/summary 동기화가 본체인 세션
- 문서 정합성 수정은 가능하면 현재 작업 턴 안에서 같이 처리합니다.
- 별도 peer-verify는 remote-visible mutation, runtime/config decision, high-risk measurement처럼 다시 읽는 비용이 정당화되는 경우에만 사용합니다.

즉, DAD는 계속 사용할 수 있지만, **DaD 관리 자체가 본체가 되면 비효율**입니다.

---

## 프로젝트 구조

```
.
├── pipeline/                  # 핵심 파이프라인 모듈
│   ├── main.py                #   오케스트레이터 (CLI 진입점)
│   ├── config.py              #   설정 관리
│   ├── settings_ui.py         #   설정 GUI (tkinter)
│   ├── models.py              #   데이터 클래스
│   ├── state.py               #   처리 상태 영속화
│   ├── utils.py               #   로깅, 리트라이, 포맷팅
│   ├── monitor.py             #   VOD 목록 폴링
│   ├── downloader.py          #   144p VOD 다운로드
│   ├── chat_collector.py      #   채팅 리플레이 수집
│   ├── chat_analyzer.py       #   하이라이트 탐지
│   ├── transcriber.py         #   Whisper 자막 생성
│   ├── chunker.py             #   SRT 청크 분할
│   ├── scraper.py             #   fmkorea 스크레이핑
│   ├── claude_cli.py          #   Claude Code CLI 래퍼
│   └── summarizer.py          #   2단계 요약 + 리포트 생성
├── content/
│   └── network.py             # Chzzk API 네트워크 유틸
├── tray_app.py                # 시스템 트레이 런처
├── transcribe.py              # Whisper 자막 생성 코어
├── split_video.py             # ffmpeg 영상 분할
├── prompts/
│   └── 청크 통합 프롬프트.md    # Claude 통합 요약 프롬프트
├── resources/
│   └── chzzk.ico              # 트레이 아이콘
├── pipeline_config.json       # 설정 파일 (자동 생성)
├── pipeline_tray.bat          # 트레이 앱 런처
├── pipeline_daemon.bat        # CLI 데몬 런처
├── requirements.txt           # Python 의존성
└── _archive/                  # 이전 프로젝트 파일 (참고용)
```

---

## 기술 스택

| 구성요소 | 기술 |
|----------|------|
| 자막 생성 | Whisper large-v3-turbo + Silero VAD |
| 채팅 분석 | Z-score 기반 피크 탐지 + 감정 키워드 가중치 |
| 커뮤니티 | BeautifulSoup + lxml (fmkorea 스크래핑) |
| AI 요약 | Claude Code CLI (stdin 파이프) |
| 시스템 트레이 | pystray + Pillow |
| 설정 UI | tkinter (Python 내장) |
| 데몬 | threading + 파일 기반 상태 관리 |

---

## 라이선스

MIT License
