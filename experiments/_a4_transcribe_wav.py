"""A4 Turn 5 helper: transcribe a single prepared .wav directly (skip split/extract).

Bypasses transcribe.py's internal split_video + extract_audio because the keyframe-copied
clip triggered a degenerate 261-byte part002 in the split step. We already have part001.wav
which contains effectively the full clip audio, and we have the raw 3h clip for fresh run.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import transcribe as T  # type: ignore


def transcribe_single(models, audio_path: str, out_srt: str) -> None:
    model, processor, device, torch_dtype, vad_model, vad_utils = models
    t0 = time.time()
    audio_np = T.load_audio(audio_path)
    speech_segments = T.get_speech_segments(audio_np, vad_model, vad_utils)
    total_duration = len(audio_np) / T.SAMPLE_RATE
    print(f"[a4-wav] audio={os.path.basename(audio_path)} duration={total_duration:.0f}s segments={len(speech_segments)}")

    entries, total_chunks = T.transcribe_audio(
        model, processor, device, torch_dtype,
        vad_model, vad_utils,
        audio_path,
        time_offset=0, part_num=1, total_parts=1,
        log_func=lambda m: None,  # suppress per-chunk log spam
        precomputed_speech_segments=speech_segments,
        preloaded_audio=audio_np,
    )
    elapsed = time.time() - t0
    print(f"[a4-wav] transcribe done: {len(entries)} entries, {total_chunks} chunks, {elapsed:.1f}s elapsed")
    T.write_srt(entries, out_srt)
    print(f"[a4-wav] wrote {out_srt}")


def main(argv: list[str]) -> int:
    if len(argv) < 3 or len(argv) % 2 != 1:
        print("usage: python _a4_transcribe_wav.py <audio_path> <out_srt_path> [<audio_path2> <out_srt_path2> ...]")
        return 2
    pairs = list(zip(argv[1::2], argv[2::2]))
    for audio_path, _ in pairs:
        if not os.path.isfile(audio_path):
            print(f"audio not found: {audio_path}")
            return 2

    print(f"[a4-wav] loading Whisper + VAD once for {len(pairs)} job(s)...")
    models = T.load_models(print)
    print(f"[a4-wav] model loaded")

    for audio_path, out_srt in pairs:
        transcribe_single(models, audio_path, out_srt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
