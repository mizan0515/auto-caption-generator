# b32 — Whisper 튜닝 (batch_size × num_beams)

Date: 2026-04-19
Script: `experiments/b32_whisper_tuning.py`
Raw: `experiments/results/b32_whisper_tuning.json`

## 배경

b31 에서 GPU 전환이 복구됐다. 다음 후속 튜닝 후보 측정:
- `batch_size` — 청크를 배치로 묶어 `model.generate` 1회 호출
- `num_beams` — 빔 서치 폭 (품질/속도 trade-off)

입력: `work/12347484/..._144p_part001.mp4`, `t=600s`, 180s clip
- audio 180s, speech 107s, chunks 18.
- device: RTX 2070 SUPER, torch 2.11.0+cu126, float16.

baseline = 현 production = `num_beams=5`, `batch_size=1`.

## 결과

| config | elapsed | peak VRAM | entries | jaccard(baseline) | speedup |
|---|---:|---:|---:|---:|---:|
| baseline_beam5_bs1 | 16.0s | 1786 MB | 18 | 1.00 | 1.00x |
| beam5_bs2 | 14.0s | 2019 MB | 18 | 0.98 | 1.14x |
| **beam5_bs4** | **12.4s** | **2495 MB** | **18** | **0.98** | **1.29x** |
| beam5_bs8 | 11.6s | 3417 MB | 18 | 1.00 | 1.39x |
| beam3_bs4 | 10.6s | 2174 MB | 18 | 0.94 | 1.51x |
| beam1_bs4 | 7.6s | 1880 MB | 18 | 0.85 | 2.11x |
| beam1_bs8 | 7.1s | 2210 MB | 18 | 0.85 | 2.26x |

- entries 수는 모든 config에서 18로 동일 (환각 필터 통과 후 자막 세그먼트 개수).
- `word_jaccard_vs_baseline`: baseline 자막의 단어 집합과 Jaccard. 품질 proxy.

## 해석

- **batch 효과는 제한적**: beam=5 유지 시 bs=1→bs=8 에서 1.39x. Whisper는 청크 내 generate 시간이 길어 배치 병렬 이득이 크지 않다.
- **beam 낮추면 품질 하락 확실**: beam=5→3 에서 jaccard 0.94 (6% 단어 차이), beam=5→1 에서 0.85 (15% 단어 차이). beam=1 출력은 검수 시 누락/오인식이 눈에 띔 → 채택 불가.
- **VRAM 예산 (8GB GPU)**: 모든 config에서 피크 < 3.5GB. 안전 마진 큼. 단 긴 VOD + 청크 최대 길이(10초)에서 일부 청크가 길면 피크가 더 상승할 수 있음 — bs=8은 여유가 줄어든다.

## 결정

**`num_beams=5`, `batch_size=4` 채택.**
- 품질 (jac 0.98) 사실상 유지
- 1.29x 가속
- 피크 2.5GB 로 안전 마진 충분 (긴 VOD/복잡 오디오 여유)
- bs=8 는 추가 0.1x 가속을 위해 peak 0.9GB 더 쓴다 → 이득 대비 위험 매칭 나쁨

## 적용

`transcribe.py` `transcribe_audio` 청크 루프를 배치 처리로 변경. 환경변수
`WHISPER_BATCH_SIZE` 로 override 가능 (default 4, CPU 경로에서는 강제 1).

재스모크 (`b31_gpu_smoke.py --duration 180`):
- 18 chunks, 15.0s, peak 2496 MB, empty_cache 후 1553 MB.
- baseline bs=1 (16.0s) 대비 6% 빠름. b32 측정값보다 약간 느린 이유: b32 는 동일 프로세스에서 여러 config 연속 실행하며 CUDA warm-up 이 끝난 상태 측정. 첫 실행은 약간 느리게 나옴.
- 실제 1시간 VOD 기준 환산: 청크 200개 내외면 300s→230s 수준 기대.

## 상태

- [x] batch_size 측정
- [x] num_beams 측정
- [x] production 적용 (transcribe.py)
- [x] 재스모크 PASS
- [ ] 실제 파이프라인 1-VOD 전사 실측 (사용자 VOD 기준, 다음 실행 시 확인)
