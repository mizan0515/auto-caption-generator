"""
b32_whisper_tuning.py — Whisper 파라미터 튜닝 측정

목적: GPU 전환 후 (b31) 다음 튜닝 포인트의 실측
- batch_size: 청크 단위 배치 크기 (1, 2, 4, 8)
- num_beams: 빔 서치 폭 (1, 3, 5)

측정:
- 전사 소요 시간 (초)
- 피크 VRAM (MB)
- 자막 entry 수
- baseline (beam=5, batch=1) 대비 텍스트 overlap (Jaccard on words)

사용:
  python experiments/b32_whisper_tuning.py [--input <mp4>] [--start <s>] [--duration <s>]

기본: part001, t=600s, 300s (5분)
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEFAULT_INPUT = ROOT / "work" / "12347484" / "12347484_구스구스덕 출발~~~ ٩(●'▿'●)۶_144p_part001.mp4"
RESULT_JSON = ROOT / "experiments" / "results" / "b32_whisper_tuning.json"


def extract_wav(mp4: Path, wav: Path, start: int, duration: int) -> None:
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", str(start), "-i", str(mp4),
        "-ac", "1", "-ar", "16000",
        "-t", str(duration), str(wav),
    ], check=True)


def run_transcribe(
    model, processor, device, torch_dtype,
    audio, chunks, prompt_ids,
    *, batch_size: int, num_beams: int, log,
):
    """
    transcribe.py transcribe_audio의 청크 루프를 재현하되
    batch_size / num_beams 를 실험한다.
    반환: (entries_text_list, elapsed_sec, peak_vram_mb)
    """
    import torch
    from transcribe import parse_whisper_tokens, is_hallucination, SAMPLE_RATE

    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    t0 = time.time()

    entries: list[dict] = []

    # 청크를 배치 단위로 묶어 generate
    for bi in range(0, len(chunks), batch_size):
        batch = chunks[bi:bi + batch_size]
        chunk_audios = [audio[s:e] for s, e in batch]
        chunk_start_secs = [s / SAMPLE_RATE for s, _ in batch]

        inputs = processor(
            chunk_audios,
            sampling_rate=SAMPLE_RATE,
            return_tensors="pt",
        )
        input_features = inputs.input_features.to(device, dtype=torch_dtype)

        with torch.no_grad():
            predicted_ids = model.generate(
                input_features,
                language="ko",
                task="transcribe",
                return_timestamps=True,
                prompt_ids=prompt_ids,
                condition_on_prev_tokens=False,
                compression_ratio_threshold=1.35,
                no_speech_threshold=0.6,
                logprob_threshold=-1.0,
                temperature=(0.0, 0.2, 0.4, 0.6, 0.8, 1.0),
                num_beams=num_beams,
                no_repeat_ngram_size=3,
                repetition_penalty=1.2,
                length_penalty=1.0,
            )

        decoded_all = processor.batch_decode(predicted_ids, skip_special_tokens=False)

        for decoded, chunk_start_sec in zip(decoded_all, chunk_start_secs):
            segs, _ = parse_whisper_tokens(decoded)
            for seg in segs:
                if is_hallucination(seg["text"]):
                    continue
                entries.append({
                    "start": seg["start"] + chunk_start_sec,
                    "end": seg["end"] + chunk_start_sec,
                    "text": seg["text"],
                })

    elapsed = time.time() - t0
    peak_mb = torch.cuda.max_memory_allocated() / (1024 * 1024)
    torch.cuda.empty_cache()
    log(f"    → {len(entries)} entries, {elapsed:.1f}s, peak {peak_mb:.0f} MB")
    return entries, elapsed, peak_mb


def word_jaccard(a_entries, b_entries) -> float:
    import re
    def tokens(entries):
        out = set()
        for e in entries:
            for w in re.findall(r"[\w']+", e["text"]):
                out.add(w)
        return out
    A = tokens(a_entries)
    B = tokens(b_entries)
    if not A and not B:
        return 1.0
    return len(A & B) / len(A | B) if (A or B) else 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=str, default=str(DEFAULT_INPUT))
    ap.add_argument("--start", type=int, default=600)
    ap.add_argument("--duration", type=int, default=300)
    ap.add_argument("--only", type=str, default=None, help="csv of config names to run")
    args = ap.parse_args()

    mp4 = Path(args.input)
    print(f"[b32] input: {mp4}")
    print(f"[b32] clip: t={args.start}s, dur={args.duration}s")

    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "clip.wav"
        extract_wav(mp4, wav, args.start, args.duration)
        print(f"[b32] wav ready ({wav.stat().st_size / 1024:.0f} KB)")

        import torch
        from transcribe import (
            load_models, load_audio, get_speech_segments, merge_vad_into_chunks,
            SAMPLE_RATE,
        )

        model, processor, device, torch_dtype, vad_model, vad_utils = load_models(print)
        print(f"[b32] device={device}, dtype={torch_dtype}")
        assert device == "cuda", "need CUDA for this experiment"

        audio = load_audio(str(wav))
        speech = get_speech_segments(audio, vad_model, vad_utils)
        chunks = merge_vad_into_chunks(speech, len(audio))
        speech_sec = sum(e - s for s, e in speech) / SAMPLE_RATE
        print(f"[b32] audio {len(audio)/SAMPLE_RATE:.0f}s, speech {speech_sec:.0f}s, chunks {len(chunks)}")

        prompt_ids = processor.get_prompt_ids(
            "안녕하세요, 환영합니다. 오늘도 재밌게 해봅시다! 자, 그러면 시작할게요.",
            return_tensors="pt",
        ).to(device)

        configs = [
            # baseline (current production)
            {"name": "baseline_beam5_bs1", "beam": 5, "batch": 1},
            # batch sweep at beam=5
            {"name": "beam5_bs2", "beam": 5, "batch": 2},
            {"name": "beam5_bs4", "beam": 5, "batch": 4},
            {"name": "beam5_bs8", "beam": 5, "batch": 8},
            # beam sweep at batch=4
            {"name": "beam3_bs4", "beam": 3, "batch": 4},
            {"name": "beam1_bs4", "beam": 1, "batch": 4},
            # aggressive
            {"name": "beam1_bs8", "beam": 1, "batch": 8},
        ]
        if args.only:
            wanted = {s.strip() for s in args.only.split(",")}
            configs = [c for c in configs if c["name"] in wanted]

        results = []
        baseline_entries = None

        for cfg in configs:
            print(f"\n[b32] >>> {cfg['name']}: beam={cfg['beam']}, batch={cfg['batch']}")
            try:
                entries, elapsed, peak = run_transcribe(
                    model, processor, device, torch_dtype,
                    audio, chunks, prompt_ids,
                    batch_size=cfg["batch"], num_beams=cfg["beam"],
                    log=print,
                )
                if cfg["name"] == "baseline_beam5_bs1":
                    baseline_entries = entries
                jac = word_jaccard(baseline_entries, entries) if baseline_entries else 1.0
                results.append({
                    **cfg,
                    "ok": True,
                    "elapsed_sec": round(elapsed, 2),
                    "peak_vram_mb": round(peak, 1),
                    "entries": len(entries),
                    "word_jaccard_vs_baseline": round(jac, 3),
                })
            except Exception as e:
                print(f"    FAIL: {type(e).__name__}: {e}")
                results.append({**cfg, "ok": False, "error": f"{type(e).__name__}: {e}"})
                torch.cuda.empty_cache()

        print("\n=== SUMMARY ===")
        header = f"{'config':<24} {'elapsed':>9} {'peak':>9} {'ents':>5} {'jac':>6} {'speedup':>8}"
        print(header)
        print("-" * len(header))
        baseline_elapsed = next(
            (r["elapsed_sec"] for r in results if r["name"] == "baseline_beam5_bs1" and r.get("ok")),
            None,
        )
        for r in results:
            if not r.get("ok"):
                print(f"{r['name']:<24}  FAIL: {r.get('error','')}")
                continue
            sp = (baseline_elapsed / r["elapsed_sec"]) if baseline_elapsed else 0
            print(
                f"{r['name']:<24} {r['elapsed_sec']:>8.1f}s "
                f"{r['peak_vram_mb']:>7.0f}MB {r['entries']:>5} "
                f"{r['word_jaccard_vs_baseline']:>6.2f} {sp:>7.2f}x"
            )

        RESULT_JSON.parent.mkdir(exist_ok=True)
        RESULT_JSON.write_text(json.dumps({
            "input": str(mp4),
            "start": args.start, "duration": args.duration,
            "audio_sec": len(audio) / SAMPLE_RATE,
            "speech_sec": speech_sec,
            "num_chunks": len(chunks),
            "results": results,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n[b32] wrote {RESULT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
