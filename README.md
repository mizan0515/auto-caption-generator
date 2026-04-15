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

스트리머 이름, 채널 ID, 검색 키워드, 쿠키 등을 GUI에서 편집할 수 있습니다.

### 방법 2: 설정 파일 직접 편집

첫 실행 시 `pipeline_config.json`이 자동 생성됩니다.

```jsonc
{
  "target_channel_id": "a7e175625fdea5a7d98428302b7aa57f",  // 채널 ID (32자리)
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
