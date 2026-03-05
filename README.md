# 자동 자막 생성기

Whisper large-v3-turbo + Silero VAD 기반 한국어 자막 자동 생성 도구.
Streamlit 웹 UI와 CLI를 모두 지원하며, 장시간 영상도 1시간 단위로 자동 분할하여 처리합니다.

---

## 주요 기능

- **고정밀 한국어 자막**: `openai/whisper-large-v3-turbo` 모델, 빔 서치(beam=5) 적용
- **VAD 기반 음성 구간 탐지**: Silero VAD로 무음 구간을 건너뛰어 처리 속도 향상
- **환각(hallucination) 자동 필터링**: 압축률 분석 + n-gram 반복 패턴 감지
- **자막 품질 자동 후처리**: 넷플릭스 기준 준수 (한 줄 42자, 최대 2줄, 7초 이하)
- **장시간 영상 지원**: 1시간 단위 자동 분할 → 처리 → SRT 병합
- **4가지 입력 모드**: 통 영상 / 분할된 영상 / 통 MP3 / 분할된 MP3
- **GPU/CPU 자동 선택**: CUDA 사용 가능 시 float16, 아니면 CPU float32
- **SRT 전처리 / 청크 분할 도구** 내장 (사이드바 추가 페이지)

---

## 요구사항

### 소프트웨어

| 항목 | 버전 |
|------|------|
| Python | 3.10 이상 권장 |
| ffmpeg | 최신 버전 |
| CUDA (선택) | 11.8 이상 (GPU 사용 시) |

### ffmpeg 설치

```bash
# Windows (WinGet)
winget install Gyan.FFmpeg

# macOS
brew install ffmpeg
```

---

## 설치

```bash
git clone https://github.com/mizan0515/auto-caption-generator.git
cd auto-caption-generator

pip install -r requirements.txt
```

> **첫 실행 시** Whisper 모델(~1.5 GB)과 Silero VAD가 자동으로 다운로드됩니다.

---

## 실행 방법

### 방법 1: 더블클릭 (Windows 권장)

```
실행.bat
```

브라우저가 자동으로 열리고 Streamlit 앱이 실행됩니다.

### 방법 2: 직접 실행

```bash
streamlit run app.py
```

브라우저에서 `http://localhost:8501` 접속.

### 방법 3: CLI

```bash
# 통 영상/MP3 한 파일
python transcribe.py video.mp4
python transcribe.py audio.mp3

# 분할된 파트 파일 여러 개
python transcribe.py --split part1.mp3 part2.mp3 part3.mp3

# 완료 후 중간 파일 자동 삭제
python transcribe.py --cleanup video.mp4
python transcribe.py --split --cleanup part1.mp3 part2.mp3
```

---

## UI 사용법

### 1. 입력 유형 선택

| 모드 | 설명 |
|------|------|
| 통 영상 | mp4, mkv, avi 등 단일 영상 파일 |
| 분할된 영상 | 미리 분할된 영상 파트 여러 개 |
| 통 MP3 | mp3, wav, m4a 등 단일 오디오 파일 |
| 분할된 MP3 | 미리 분할된 오디오 파트 여러 개 |

### 2. 파일 선택

- **📂 버튼** 클릭 → 파일 탐색기에서 선택
- 경로를 **직접 입력**도 가능
- 분할 모드: 여러 파일 선택 후 순서 확인, 개별 ✕ 버튼으로 제거 가능

### 3. 옵션

- **완료 후 임시 파일 자동 삭제**: 체크 시 처리 완료 후 분할 파트, WAV, 병합 파일 자동 제거 (원본은 보존)

### 4. 실행

- **▶ 자막 생성 시작** 버튼 클릭
- 실시간 진행률 바 및 로그 확인
- 완료 시 SRT 저장 경로 표시 + **📁 출력 폴더 열기** 버튼

---

## 처리 파이프라인 (7단계)

```
[입력 파일]
    │
    ▼ (분할 파일 모드만)
0단계. 파트 병합 (ffmpeg concat)
    │
    ▼
1단계. 1시간 단위 분할 (ffmpeg -c copy, 재인코딩 없음)
    │
    ▼
2단계. 음성 추출 → WAV 16kHz mono (ffmpeg)
    │
    ▼
3단계. 모델 로드
        - Whisper large-v3-turbo (HuggingFace Transformers)
        - Silero VAD (torch.hub)
    │
    ▼
    VAD 사전 스캔 → 전체 청크 수 계산 (진행률 정확화)
    │
    ▼
4단계. 자막 생성
        - Silero VAD로 음성 구간만 추출 (무음 건너뜀)
        - 최대 10초 단위 청크로 분할
        - Whisper 디코딩 (빔 서치 5, 환각 방지 파라미터)
        - 환각 필터: 압축률 + n-gram 반복 감지
    │
    ▼
5단계. 후처리
        - 너무 짧은 자막 제거 (< 0.5초)
        - 긴 자막 분할 (문장 부호 기준, 최대 7초)
        - 인접 자막 병합 (간격 < 0.1초)
        - 타임스탬프 겹침 보정
    │
    ▼
6단계. SRT 저장 (원본 파일과 동일 경로)
    │
    ▼ (cleanup 옵션 시)
7단계. 임시 파일 정리 (분할 파트, WAV, 병합 파일)
```

---

## SRT 품질 기준

| 항목 | 값 | 기준 |
|------|----|------|
| 한 줄 최대 글자수 | 42자 | 넷플릭스 표준 |
| 최대 줄 수 | 2줄 | 넷플릭스 표준 |
| 최소 지속시간 | 0.5초 | 가독성 |
| 최대 지속시간 | 7.0초 | 가독성 |
| 자막 간 최소 간격 | 0.1초 | 겹침 방지 |

---

## 환각 방지 메커니즘

Whisper는 반복 텍스트를 생성하는 환각 현상이 발생할 수 있습니다. 아래 3가지 방법으로 필터링합니다.

1. **압축률 분석**: zlib 압축률이 2.0 이상이면 환각으로 판단 (반복 텍스트는 압축률이 높음)
2. **n-gram 반복 감지**: 2~5어절 조합이 3회 이상 반복되면 제거
3. **단일 단어 반복 감지**: 동일 단어만 3회 이상 반복되면 제거

추가로 Whisper 생성 파라미터에서도 방지:
- `condition_on_prev_tokens=False`
- `no_repeat_ngram_size=3`
- `repetition_penalty=1.2`
- `temperature=(0.0, 0.2, 0.4, 0.6, 0.8, 1.0)` — 다중 온도 폴백

---

## 추가 페이지 (사이드바)

### SRT 전처리 — 고밀도 구간 추출

자막이 밀집된 구간(자막 밀도가 높은 부분)만 추출하여 별도 SRT로 저장합니다.
강의, 토론, 인터뷰 등에서 핵심 발화 구간만 뽑아낼 때 유용합니다.

- SRT 파일 업로드
- 시간 창(분) / 밀도 임계값 설정
- 추출된 고밀도 구간 SRT 다운로드

### SRT 청크 분할 — LLM 투입용 txt 생성

긴 SRT를 LLM에 투입하기 적합한 크기의 청크로 분할합니다.
번역, 교정, 요약 등 LLM 후처리 작업에 활용합니다.

- 청크 최대 길이 설정: 시간(초) 또는 글자 수 기준
- 청크 간 오버랩(초) 설정으로 문맥 연속성 보장
- ZIP으로 전체 청크 + `manifest.json` 다운로드

---

## 프로젝트 구조

```
auto-caption-generator/
├── app.py                  # Streamlit 메인 페이지 (자막 생성)
├── transcribe.py           # 핵심 자막 생성 엔진
├── split_video.py          # ffmpeg 래퍼 (분할, 음성 추출, 길이 조회)
├── merge.py                # ffmpeg concat 래퍼 (파트 병합)
├── launcher.py             # Streamlit 자동 실행 + 브라우저 오픈
├── 실행.bat                # Windows 더블클릭 실행 파일
├── requirements.txt        # pip 의존성 목록
└── pages/
    ├── SRT_전처리.py       # 고밀도 구간 추출 페이지
    └── SRT_청크분할.py     # LLM 투입용 청크 분할 페이지
```

---

## 분할 파일 파일명 패턴

`--split` 모드에서 파일명에 시간 정보가 포함되어 있으면 자동으로 파싱하여 정확한 타임스탬프를 적용합니다.

```
[제목] - Part 1 (00-00-00 to 01-00-01).mp3
[제목] - Part 2 (01-00-01 to 02-00-02).mp3
```

패턴이 없는 경우 파일 순서 기준으로 1시간씩 오프셋을 자동 할당합니다.

---

## 주의사항

- **첫 실행 시** Whisper 모델 약 1.5 GB가 HuggingFace 캐시로 다운로드됩니다.
- **GPU 없는 환경(CPU)**: 처리 속도가 크게 느려집니다. 1시간 영상 기준 수 시간 소요될 수 있습니다.
- **ffmpeg 필수**: PATH에 ffmpeg가 없으면 WinGet 설치 경로에서 자동으로 찾습니다. 없으면 오류가 발생합니다.
- **원본 파일은 삭제되지 않습니다.** `cleanup` 옵션은 중간 생성 파일(분할 파트, WAV, 병합 파일)만 삭제합니다.
