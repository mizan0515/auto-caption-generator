"""faster-whisper vs HF transformers (large-v3-turbo) 벤치마크.

사용: python experiments/faster_whisper_bench.py <wav_path> [--duration-sec 300]

측정:
  - HF transformers (현재 파이프라인): fp16, CUDA
  - faster-whisper fp16
  - faster-whisper int8_float16

비교 지표: wall time, RTF (real-time factor), 첫 300초 텍스트 Diff 여부.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


def bench_hf(wav: str, duration_sec: int) -> dict:
    import torch
    import librosa
    from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor, pipeline

    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    model_id = "openai/whisper-large-v3-turbo"
    audio, sr = librosa.load(wav, sr=16000, duration=duration_sec)
    model = AutoModelForSpeechSeq2Seq.from_pretrained(
        model_id, torch_dtype=torch.float16, low_cpu_mem_usage=True
    ).to(device)
    processor = AutoProcessor.from_pretrained(model_id)
    pipe = pipeline(
        "automatic-speech-recognition",
        model=model,
        tokenizer=processor.tokenizer,
        feature_extractor=processor.feature_extractor,
        torch_dtype=torch.float16,
        device=device,
        chunk_length_s=30,
    )
    t0 = time.time()
    out = pipe(audio, generate_kwargs={"language": "ko", "task": "transcribe"})
    dt = time.time() - t0
    return {"backend": "hf-transformers", "sec": round(dt, 2), "rtf": round(dt / duration_sec, 3), "text_head": out["text"][:200]}


def _gpu_mem_mb() -> int:
    try:
        import torch
        if torch.cuda.is_available():
            return int(torch.cuda.memory_allocated() / 1024 / 1024)
    except Exception:
        pass
    return -1


def bench_fw(wav: str, duration_sec: int, compute_type: str) -> dict:
    from faster_whisper import WhisperModel
    import librosa, soundfile as sf, tempfile, os

    audio, sr = librosa.load(wav, sr=16000, duration=duration_sec)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        tmp = f.name
    sf.write(tmp, audio, sr)
    try:
        print(f"  loading faster-whisper (device=cuda, compute={compute_type})...")
        model = WhisperModel("large-v3-turbo", device="cuda", compute_type=compute_type)
        # ctranslate2 uses its own allocator; torch.cuda.memory_allocated won't see it.
        # Use nvidia-smi if available for a sanity check.
        import subprocess
        try:
            smi = subprocess.check_output(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], text=True, timeout=5).strip()
            print(f"  nvidia-smi post-load memory.used = {smi} MiB")
        except Exception:
            smi = "n/a"
        t0 = time.time()
        segments, info = model.transcribe(tmp, language="ko", beam_size=1, vad_filter=False)
        text = " ".join(s.text for s in segments)
        dt = time.time() - t0
        try:
            smi2 = subprocess.check_output(["nvidia-smi", "--query-gpu=memory.used,utilization.gpu", "--format=csv,noheader,nounits"], text=True, timeout=5).strip()
            print(f"  nvidia-smi post-transcribe = {smi2}")
        except Exception:
            smi2 = "n/a"
    finally:
        os.unlink(tmp)
    return {
        "backend": f"faster-whisper-{compute_type}",
        "sec": round(dt, 2),
        "rtf": round(dt / duration_sec, 3),
        "gpu_mem_mib_post_load": smi,
        "gpu_after_transcribe": smi2,
        "text_head": text[:200],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("wav")
    ap.add_argument("--duration-sec", type=int, default=300)
    ap.add_argument("--skip-hf", action="store_true")
    args = ap.parse_args()

    results = []
    if not args.skip_hf:
        print("=== HF transformers ===")
        results.append(bench_hf(args.wav, args.duration_sec))
        print(results[-1])
    print("=== faster-whisper fp16 ===")
    results.append(bench_fw(args.wav, args.duration_sec, "float16"))
    print(results[-1])
    print("=== faster-whisper int8_float16 ===")
    results.append(bench_fw(args.wav, args.duration_sec, "int8_float16"))
    print(results[-1])

    out_path = Path("experiments/results/faster_whisper_bench.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nsaved: {out_path}")


if __name__ == "__main__":
    main()
