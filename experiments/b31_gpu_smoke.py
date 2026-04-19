"""
b31_gpu_smoke.py — Whisper GPU 전환 스모크

목적:
- torch CUDA 빌드 재설치 후 transcribe_audio 가 실제로 cuda 경로를 타는지 검증
- 짧은 MP4 1개로 최소 실행, 시작 전/후 VRAM, 청크당 시간, empty_cache 효과 측정

사용:
  python experiments/b31_gpu_smoke.py [--input <path.mp4>]

입력 생략 시 work/12801656_slice_verify/*.mp4 중 첫 파일 사용.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def find_default_input() -> Path:
    candidates = list((ROOT / "work" / "12801656_slice_verify").glob("*.mp4"))
    if not candidates:
        candidates = list((ROOT / "work" / "12801656_m3u8_smoke").glob("*.mp4"))
    if not candidates:
        raise SystemExit("no default mp4 under work/12801656_slice_verify or _m3u8_smoke")
    return candidates[0]


def extract_wav(mp4: Path, wav: Path, start: int = 0, duration: int = 120) -> None:
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", str(start),
        "-i", str(mp4),
        "-ac", "1", "-ar", "16000",
        "-t", str(duration),
        str(wav),
    ]
    subprocess.run(cmd, check=True)


def vram_mb() -> float:
    import torch
    if not torch.cuda.is_available():
        return 0.0
    return torch.cuda.memory_allocated() / (1024 * 1024)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=str, default=None)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--duration", type=int, default=120)
    args = ap.parse_args()

    mp4 = Path(args.input) if args.input else find_default_input()
    print(f"[smoke] input: {mp4}")
    print(f"[smoke] exists: {mp4.exists()}  size: {mp4.stat().st_size if mp4.exists() else 'n/a'}")

    import torch
    print(f"[smoke] torch: {torch.__version__}")
    print(f"[smoke] cuda available: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"[smoke] device: {torch.cuda.get_device_name(0)}")
        print(f"[smoke] total vram: {torch.cuda.get_device_properties(0).total_memory / (1024**3):.1f} GB")

    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "clip.wav"
        print(f"[smoke] extracting {args.duration}s from t={args.start}s (mono 16k wav) ...")
        t0 = time.time()
        extract_wav(mp4, wav, start=args.start, duration=args.duration)
        print(f"[smoke] wav ready in {time.time() - t0:.1f}s, size {wav.stat().st_size / 1024:.0f} KB")

        from transcribe import load_models, transcribe_audio

        print(f"[smoke] VRAM before load: {vram_mb():.1f} MB")
        t_load = time.time()
        model, processor, device, torch_dtype, vad_model, vad_utils = load_models(print)
        print(f"[smoke] load_models took {time.time() - t_load:.1f}s")
        print(f"[smoke] device reported: {device}")
        print(f"[smoke] dtype: {torch_dtype}")
        print(f"[smoke] VRAM after load: {vram_mb():.1f} MB")

        if device != "cuda":
            print("[smoke] FAIL: device is not cuda — GPU path not engaged")
            return 1

        t_tx = time.time()
        entries, total_chunks = transcribe_audio(
            model, processor, device, torch_dtype,
            vad_model, vad_utils,
            str(wav),
            time_offset=0, part_num=1, total_parts=1,
            log_func=print,
        )
        elapsed = time.time() - t_tx
        print(f"[smoke] transcribe took {elapsed:.1f}s for {total_chunks} chunks → {len(entries)} entries")
        print(f"[smoke] VRAM after transcribe (post empty_cache): {vram_mb():.1f} MB")

        # empty_cache 가 호출됐는지 간접 확인: transcribe 후 VRAM이 peak 대비 내려가 있어야 함
        if torch.cuda.is_available():
            peak = torch.cuda.max_memory_allocated() / (1024 * 1024)
            print(f"[smoke] peak VRAM during transcribe: {peak:.1f} MB")

    print("[smoke] PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
