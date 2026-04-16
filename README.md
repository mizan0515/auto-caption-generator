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

## 설치

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
