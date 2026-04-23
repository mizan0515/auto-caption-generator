"""faster-whisper vs HF transformers — 파라미터 완전 동등 벤치마크 v2.

파이프라인 실제 설정 (transcribe.py:588-604) 을 양쪽에 맞춘다:
  beam=5, temperature fallback, compression_ratio=1.35,
  no_speech=0.6, logprob=-1.0, condition_on_prev=False,
  no_repeat_ngram=3, repetition_penalty=1.2, length_penalty=1.0.

VAD: Silero threshold=0.5, min_speech=250ms, min_silence=500ms, pad=300ms.

사용:
  python experiments/faster_whisper_bench_v2.py <wav> [--duration-sec 600]
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def slice_audio(src_wav: str, out_wav: str, duration_sec: int) -> None:
    """ffmpeg 로 앞 N초 슬라이스 (리샘플 없음)."""
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-i", src_wav,
        "-t", str(duration_sec),
        "-c", "copy",
        out_wav,
    ]
    subprocess.run(cmd, check=True)


def nvsmi() -> str:
    try:
        return subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            text=True, timeout=5,
        ).strip()
    except Exception:
        return "n/a"


def _silence_logger():
    return lambda *a, **kw: None


def run_arm_a(wav: str) -> dict:
    """Arm A: 실제 파이프라인 transcribe_audio() 재사용."""
    import transcribe as T
    import torch

    log = _silence_logger()
    model, processor, device, dtype, vad_model, vad_utils = T.load_models(log_func=log)

    # warm-up: 짧은 30s 파일이 없으니 동일 wav 앞부분에 대해 간단한 VAD+GPU 워밍.
    audio = T.load_audio(wav)
    # 워밍업: 30s 서브셋으로 VAD+1 chunk transcribe (시간 측정 제외)
    _ = T.get_speech_segments(audio[: 30 * T.SAMPLE_RATE], vad_model, vad_utils)

    torch.cuda.synchronize()
    mem_before = nvsmi()
    t0 = time.time()
    entries, total_chunks = T.transcribe_audio(
        model, processor, device, dtype,
        vad_model, vad_utils,
        wav,
        time_offset=0, part_num=1, total_parts=1,
        log_func=log,
        progress_func=None,
        initial_prompt_text=None,
    )
    torch.cuda.synchronize()
    dt = time.time() - t0
    mem_after = nvsmi()

    text = " ".join(e["text"] for e in entries)
    result = {
        "arm": "A_hf_pipeline",
        "sec": round(dt, 2),
        "segments": len(entries),
        "chars": len(text),
        "chunks": total_chunks,
        "vram_before_mib": mem_before,
        "vram_after_mib": mem_after,
        "head": text[:200],
        "mid": text[len(text) // 2 : len(text) // 2 + 200] if text else "",
        "tail": text[-200:] if text else "",
    }

    del model, processor, vad_model
    gc.collect()
    torch.cuda.empty_cache()
    return result


def run_arm_fw(wav: str, compute_type: str) -> dict:
    """Arm B/C: faster-whisper, 파이프라인 파라미터 매핑."""
    from faster_whisper import WhisperModel
    import torch

    vad_params = dict(
        threshold=0.5,
        min_speech_duration_ms=250,
        min_silence_duration_ms=500,
        speech_pad_ms=300,
    )

    print(f"  loading fw large-v3-turbo ({compute_type})...")
    model = WhisperModel("large-v3-turbo", device="cuda", compute_type=compute_type)

    # warm-up: 30s 구간을 임시 파일로 만들어 돌림
    import tempfile
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", wav, "-t", "30", "-c", "copy", tmp],
        check=True,
    )
    try:
        segs, _ = model.transcribe(tmp, language="ko", beam_size=1, vad_filter=False)
        _ = list(segs)  # consume
    finally:
        os.unlink(tmp)

    mem_before = nvsmi()
    t0 = time.time()
    segments, info = model.transcribe(
        wav,
        language="ko",
        task="transcribe",
        beam_size=5,
        temperature=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
        compression_ratio_threshold=1.35,
        no_speech_threshold=0.6,
        log_prob_threshold=-1.0,
        condition_on_previous_text=False,
        repetition_penalty=1.2,
        no_repeat_ngram_size=3,
        length_penalty=1.0,
        vad_filter=True,
        vad_parameters=vad_params,
    )
    segments_list = list(segments)  # actual compute happens here
    dt = time.time() - t0
    mem_after = nvsmi()

    text = " ".join(s.text for s in segments_list)
    result = {
        "arm": f"fw_{compute_type}",
        "sec": round(dt, 2),
        "segments": len(segments_list),
        "chars": len(text),
        "vram_before_mib": mem_before,
        "vram_after_mib": mem_after,
        "head": text[:200],
        "mid": text[len(text) // 2 : len(text) // 2 + 200] if text else "",
        "tail": text[-200:] if text else "",
    }

    del model
    gc.collect()
    torch.cuda.empty_cache()
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("wav")
    ap.add_argument("--duration-sec", type=int, default=600)
    ap.add_argument("--skip-a", action="store_true")
    ap.add_argument("--skip-b", action="store_true")
    ap.add_argument("--skip-c", action="store_true")
    args = ap.parse_args()

    # 슬라이스
    tmp_wav = str(Path("work/_bench_slice.wav").resolve())
    Path(tmp_wav).parent.mkdir(parents=True, exist_ok=True)
    print(f"[slice] {args.wav} → {tmp_wav} ({args.duration_sec}s)")
    slice_audio(args.wav, tmp_wav, args.duration_sec)

    results = []
    if not args.skip_a:
        print("\n=== Arm A: HF pipeline (transcribe_audio) ===")
        r = run_arm_a(tmp_wav)
        print(json.dumps(r, ensure_ascii=False, indent=2))
        results.append(r)
    if not args.skip_b:
        print("\n=== Arm B: faster-whisper fp16 ===")
        r = run_arm_fw(tmp_wav, "float16")
        print(json.dumps(r, ensure_ascii=False, indent=2))
        results.append(r)
    if not args.skip_c:
        print("\n=== Arm C: faster-whisper int8_float16 ===")
        r = run_arm_fw(tmp_wav, "int8_float16")
        print(json.dumps(r, ensure_ascii=False, indent=2))
        results.append(r)

    # 요약
    print("\n=== Summary ===")
    base = next((r for r in results if r["arm"] == "A_hf_pipeline"), None)
    for r in results:
        line = f"  {r['arm']:28s} time={r['sec']:>7.2f}s segs={r['segments']:>4d} chars={r['chars']:>6d}"
        if base and r is not base and base["sec"]:
            speedup = base["sec"] / r["sec"] if r["sec"] else float("inf")
            completeness = r["chars"] / base["chars"] if base["chars"] else 0
            line += f"  speedup={speedup:.2f}x  completeness={completeness*100:.0f}%"
        print(line)

    out = Path("experiments/results/faster_whisper_bench_v2.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"duration_sec": args.duration_sec, "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nsaved: {out}")


if __name__ == "__main__":
    main()
