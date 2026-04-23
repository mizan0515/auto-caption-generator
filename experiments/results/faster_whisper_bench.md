# faster-whisper vs HF transformers — 벤치마크 리포트

**일자**: 2026-04-23
**GPU**: NVIDIA GeForce RTX 2070 SUPER (8GB VRAM)
**모델**: `openai/whisper-large-v3-turbo` (HF) / `large-v3-turbo` (faster-whisper CTranslate2)
**입력**: `12862847_압도적긍정적 원딜_144p_part001.wav` 앞 600초 (실 VOD 자료)

## 결론

**faster-whisper 전환 중단 권고.** 속도 이득 1.26x 는 전환 비용 + 품질 저하를 상쇄하지 못한다.

---

## v1 벤치 (오표본) — 폐기

| 백엔드 | 300s 처리 | RTF |
|---|---|---|
| HF transformers (`pipeline`, `chunk_length_s=30`) | 6.17s | 0.021 |
| faster-whisper fp16 (`vad_filter=False`) | 12.85s | 0.043 |
| faster-whisper int8_float16 (`vad_filter=False`) | 10.18s | 0.034 |

### v1 이 왜 틀렸나

파이프라인 (`transcribe.py:588-604`) 과 파라미터가 **6가지 이상 불일치**:

| 항목 | 실제 파이프라인 | v1 HF | v1 fw |
|---|---|---|---|
| `beam_size` | 5 | 1 | 1 |
| temperature fallback | `(0, 0.2, …, 1.0)` | 없음 | 없음 |
| `compression_ratio_threshold` | 1.35 | 미지정 | 미지정 |
| `condition_on_prev_tokens` | False | N/A | N/A |
| VAD | Silero 사전분할 | 없음 | `vad_filter=False` |
| chunking | 10s VAD 묶음 | 30s 균등 | 내장 30s 윈도우 |

결과는 **서로 다른 일을 하는 시스템의 시간 비교**.

- HF 48x RTF: [transformers#29595](https://github.com/huggingface/transformers/issues/29595) 의 chunked-short-form 조기종료 버그 + greedy decode.
- fw 루핑 (`쩔어 쩔어…`, `쪼롱 쪼롱…`): VAD off → 무음에서 환각 루프 → 디코더가 max_length 까지 생성.

공개 벤치 ([deepdml RTX 2080 Ti](https://huggingface.co/deepdml/faster-whisper-large-v3-turbo-ct2/discussions/3)) 에서 fw turbo fp16 RTF ≈ 0.025. RTX 2070 Super 는 그보다 1.2–1.4x 느린 0.03–0.05 가 정상 범위. v1 의 "HF 가 빠르다" 는 측정 아티팩트.

---

## v2 벤치 (공정 비교) — 본 결과

### 파라미터 매핑

파이프라인 `model.generate(...)` 파라미터를 faster-whisper `transcribe(...)` 에 1:1 매핑:

| HF (`generate`) | faster-whisper (`transcribe`) | 값 |
|---|---|---|
| `num_beams` | `beam_size` | 5 |
| `temperature` (tuple) | `temperature` (list) | `[0, 0.2, 0.4, 0.6, 0.8, 1.0]` |
| `compression_ratio_threshold` | `compression_ratio_threshold` | 1.35 |
| `no_speech_threshold` | `no_speech_threshold` | 0.6 |
| `logprob_threshold` | `log_prob_threshold` | -1.0 |
| `condition_on_prev_tokens` | `condition_on_previous_text` | False |
| `no_repeat_ngram_size` | `no_repeat_ngram_size` | 3 |
| `repetition_penalty` | `repetition_penalty` | 1.2 |
| `length_penalty` | `length_penalty` | 1.0 |

VAD: `vad_parameters={threshold:0.5, min_speech_duration_ms:250, min_silence_duration_ms:500, speech_pad_ms:300}` 로 파이프라인 Silero 세팅 복제.

HF arm 은 `transcribe.py::transcribe_audio()` 를 그대로 호출하여 파이프라인 경로 재현.

### 결과 (600초 오디오)

| Arm | 시간 | seg 수 | 문자수 | speedup | 완전성 | VRAM |
|---|---|---|---|---|---|---|
| **A: HF 파이프라인** | **25.39s** | 30 | 910 | 1.00x | — | 4.0GB |
| **B: fw fp16** | 20.19s | 64 | 859 | **1.26x** | 94% | 4.5GB |
| **C: fw int8_float16** | 23.85s | 61 | 826 | 1.06x | 91% | 3.5GB |

RTF: A=0.042, B=0.034, C=0.040.

### 품질 비교 — 스팟체크

동일 구간 텍스트 샘플.

**고유명사/인명 일관성**

| 구간 | HF | fw fp16 |
|---|---|---|
| 스트리머명 | "따효니" | "따현이" |
| 구독자 닉 | "엠비룸님" | "Plニeru님" |
| 캐릭터명 | "키리토" | "키랅토 링크" |

**이물질 토큰 (외국어 삽입)**

fw 출력에만 나타나는 노이즈:
- `Prter`, `Plニeru` (일본어 가타카나 혼입)
- `illustratedamente` (스페인어 부사 환각)
- `hein`, `\ufffd` (비토큰)

HF 출력에는 이런 혼입 0건.

**추정 원인**

fw 의 CTranslate2 디코더가 language 강제 (`language="ko"`) 하에서도 다국어 토큰을 일부 방출. 파이프라인의 `is_hallucination()` 후처리 같은 방어막 없이 그대로 세그먼트에 남음.

### 세그먼트 granularity

- HF: 30 세그먼트 (파이프라인의 `merge_vad_into_chunks(max_chunk_sec=10)` 때문)
- fw: 64 세그먼트 (VAD+30s 윈도우의 자동 분할)

fw 가 더 잘게 쪼개지는 건 자막 타이밍 측면에서는 이점이 될 수 있으나, 현재 파이프라인이 이미 10s 청크로 제어 중이므로 부가가치 없음.

---

## 속도 + 품질 통합 평가

| 축 | 평가 |
|---|---|
| 속도 | fw fp16 1.26x. **판정 기준 2.0x 미달** |
| 품질 — 고유명사 | HF 승 (일관성) |
| 품질 — 이물질 | HF 승 (외국어 혼입 0) |
| 품질 — 완전성 | 동률 (91–94%) |
| VRAM | HF 약간 적음 (4.0 vs 4.5GB) |
| 전환 비용 | 중 (dep 추가, API 차이, VAD 통합 재작업) |
| 유지보수 | HF 파이프라인은 이미 is_hallucination / lexicon / 10s 청크 통합 완료 |

**종합**: 속도 이득 1.26x 는 품질 저하 (스트리머명·구독자명 불일치, 외국어 혼입) + 전환·유지보수 비용을 상쇄하지 못한다.

---

## 더 중요한 발견 — **진짜 병목은 Whisper 가 아님**

**HF 파이프라인이 600초 오디오를 25.39초에 처리.** RTF 0.042, 24x realtime.

2시간 VOD (7200s) 환산: `25.39 × 12 = 305s ≈ 5분`.

그러나 실제 VOD 1편 처리에 **"2–3시간"** 소요된다고 사용자 관측. **차이 30배 이상**.

즉 전체 파이프라인의 시간은 Whisper 가 아닌 다른 단계에서 소모된다. 차기 조사 대상:

1. **VOD 다운로드** (144p 이어도 네트워크 IO)
2. **chat scrape** (live chat API 순차 호출, chzzk)
3. **fmkorea scrape** (레이트리밋 후 백오프)
4. **summarizer** (Claude CLI 청크 직렬 호출, 30s+ per chunk)
5. **VAD 사전 스캔** (`total_chunks_global` 계산 시 중복 수행)
6. **ffmpeg 분할** (part 단위 인코딩)

다음 실험은 실제 VOD 1편 풀 파이프라인에 stage-timing 로깅을 패치하여 실측 프로파일을 뜨는 것이 우선.

---

## 재현 방법

```bash
pip install faster-whisper librosa soundfile
python experiments/faster_whisper_bench_v2.py \
    "work/12862847/12862847_압도적긍정적 원딜_144p_part001.wav" \
    --duration-sec 600
```

결과 JSON: `experiments/results/faster_whisper_bench_v2.json`
전체 실행 로그: `experiments/results/bench_v2_run.log`

## 참고 자료

- [deepdml faster-whisper-turbo-ct2 benchmark (RTX 2080 Ti)](https://huggingface.co/deepdml/faster-whisper-large-v3-turbo-ct2/discussions/3)
- [SYSTRAN/faster-whisper README](https://github.com/SYSTRAN/faster-whisper)
- [transformers#29595 — no_speech_threshold ignored with chunking](https://github.com/huggingface/transformers/issues/29595)
- [arXiv 2501.11378 — Whisper hallucinations on non-speech](https://arxiv.org/html/2501.11378v1)
