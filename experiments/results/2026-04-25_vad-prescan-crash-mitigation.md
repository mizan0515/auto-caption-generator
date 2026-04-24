# 2026-04-25 VAD Prescan Crash Mitigation

## 배경

- `12890507` 처리 중 `VAD 사전 분석 중 (병렬, workers=4)...` 직후 로그가 끊김.
- Windows 이벤트 로그에 `pythonw.exe` / `ntdll.dll` / `0xc0000374` APPCRASH 확인.
- 사용자 팝업도 `메모리를 read될 수 없습니다`로 일치.

## 판단

- 순수 Python 예외가 아니라 네이티브 계층 크래시다.
- 재현 지점이 Silero VAD prescan 병렬 구간과 일치한다.
- 공유 VAD 모델을 여러 스레드에서 동시에 사용하는 현재 구현을 가장 유력한 트리거로 판단.

## 변경

- `transcribe.py`
  - `resolve_vad_prescan_workers()` 추가
  - 기본 prescan worker 를 `1`로 강제
  - worker 가 `1`이면 직렬 실행
  - `workers>1`일 때만 실험적 경고 출력
- `pipeline/config.py`
  - `whisper_vad_prescan_workers` 기본값 `1` 추가
- `pipeline/main.py`, `pipeline/transcriber.py`
  - config 값을 transcribe 호출로 전달
- `pipeline/settings_ui.py`, `README.md`
  - 운영 설정/가이드 추가

## 검증

- `python -c "from pipeline.transcriber import transcribe_video; print('ok')"`
- `python -c "from pipeline.config import load_config; cfg=load_config(); print(cfg['whisper_vad_prescan_workers'])"`
- `python experiments/test_vad_prescan_workers.py`

## 남은 리스크

- root cause 가 torch/cuda 또는 silero 자체라면 직렬화만으로 100% 해소되지 않을 수 있다.
- 그 경우 다음 단계는 transcriber subprocess 격리 또는 CPU/VAD fallback 이다.
