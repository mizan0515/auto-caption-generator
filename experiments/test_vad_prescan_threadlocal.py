"""VAD 사전 스캔 병렬화 검증 — per-thread VAD 모델 인스턴스 방식.

배경:
    공유 Silero VAD 모델을 여러 스레드에서 동시 호출하면 내부 RNN 버퍼
    (model.reset_states() 포함) 가 mutate 되어 heap corruption (0xc0000374) 발생.
    → 스레드마다 자기 모델 인스턴스를 갖게 하면 공유 상태가 없어 안전해야 한다.

검증 절차:
    1. 실제 WAV part 3~4개를 고른다.
    2. Sequential 베이스라인: workers=1 로 segments/chunks 기록.
    3. Parallel (per-thread model): workers=2, 4 로 반복. 결과가 sequential 과
       완전히 일치하고, 네이티브 크래시 없이 정상 종료해야 통과.
    4. 실패 시 예외/결과 차이를 표준출력에 남긴다.

사용:
    python experiments/test_vad_prescan_threadlocal.py
"""

from __future__ import annotations

import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# transcribe 모듈은 import 비용이 크니 함수 내부에서 지연 import 한다.


WORK_DIR_CANDIDATES = [
    PROJECT_ROOT / "work" / "12347484",
    PROJECT_ROOT / "work" / "12663010",
]
MAX_PARTS = 4   # 검증용으로 충분 (5분 이내 완료 목표)


def _pick_wavs() -> list[Path]:
    for work_dir in WORK_DIR_CANDIDATES:
        if not work_dir.exists():
            continue
        wavs = sorted(work_dir.glob("*_part*.wav"))
        if len(wavs) >= 2:
            return wavs[:MAX_PARTS]
    raise FileNotFoundError(
        f"테스트용 WAV 를 찾지 못했습니다. 후보: {WORK_DIR_CANDIDATES}"
    )


def _load_silero_vad():
    """독립적인 Silero VAD 인스턴스 하나를 로드한다."""
    import torch

    model, utils = torch.hub.load(
        repo_or_dir="snakers4/silero-vad",
        model="silero_vad",
        force_reload=False,
        trust_repo=True,
        verbose=False,
    )
    return model, utils


def _prescan_with_model(wav_path: Path, vad_model, vad_utils):
    from transcribe import get_speech_segments, load_audio, merge_vad_into_chunks

    audio = load_audio(str(wav_path))
    segs = get_speech_segments(audio, vad_model, vad_utils)
    chunks = merge_vad_into_chunks(segs, len(audio))
    # segs 는 (start_sample, end_sample) 튜플 리스트. hashable 로 캐스팅.
    seg_tuple = tuple((int(s), int(e)) for s, e in segs)
    return seg_tuple, len(chunks), len(audio)


def run_sequential(wavs: list[Path]):
    vad_model, vad_utils = _load_silero_vad()
    results = []
    t0 = time.time()
    for w in wavs:
        results.append(_prescan_with_model(w, vad_model, vad_utils))
    return results, time.time() - t0


def run_parallel_threadlocal(wavs: list[Path], workers: int):
    """스레드마다 자기 VAD 모델 인스턴스를 만들어 사용."""
    tlocal = threading.local()

    def _get_tl_vad():
        m = getattr(tlocal, "model", None)
        if m is None:
            tlocal.model, tlocal.utils = _load_silero_vad()
        return tlocal.model, tlocal.utils

    def _task(wav_path: Path):
        m, u = _get_tl_vad()
        return _prescan_with_model(wav_path, m, u)

    results: list[object] = [None] * len(wavs)
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_task, w): i for i, w in enumerate(wavs)}
        for fut in as_completed(futures):
            i = futures[fut]
            results[i] = fut.result()
    return results, time.time() - t0


def compare(label: str, baseline, candidate) -> bool:
    if len(baseline) != len(candidate):
        print(f"[FAIL] {label}: 결과 개수 불일치 ({len(baseline)} vs {len(candidate)})")
        return False
    all_ok = True
    for i, (b, c) in enumerate(zip(baseline, candidate)):
        b_segs, b_chunks, b_len = b
        c_segs, c_chunks, c_len = c
        if b_len != c_len:
            print(f"[FAIL] {label}[{i}]: audio len 불일치 {b_len} vs {c_len}")
            all_ok = False
            continue
        if b_chunks != c_chunks:
            print(f"[FAIL] {label}[{i}]: chunk count {b_chunks} vs {c_chunks}")
            all_ok = False
        if b_segs != c_segs:
            print(
                f"[FAIL] {label}[{i}]: segments 불일치 "
                f"(baseline {len(b_segs)}, candidate {len(c_segs)})"
            )
            # 차이 처음 3개
            diff_idx = 0
            for j, (bs, cs) in enumerate(zip(b_segs, c_segs)):
                if bs != cs:
                    print(f"    seg[{j}] baseline={bs} candidate={cs}")
                    diff_idx += 1
                    if diff_idx >= 3:
                        break
            all_ok = False
    return all_ok


def main():
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    wavs = _pick_wavs()
    print(f"[info] 테스트 대상 WAV {len(wavs)}개:")
    for w in wavs:
        print(f"  - {w}")

    print("\n[1/3] Sequential 베이스라인 실행 중...")
    baseline, t_seq = run_sequential(wavs)
    print(f"  sequential 소요: {t_seq:.1f}s")
    for i, (segs, chunks, alen) in enumerate(baseline):
        print(f"  part{i + 1}: segments={len(segs)} chunks={chunks} audio_samples={alen}")

    all_pass = True
    for workers in (2, 4):
        print(f"\n[{'2/3' if workers == 2 else '3/3'}] Parallel (per-thread VAD, workers={workers}) 실행 중...")
        try:
            candidate, t_par = run_parallel_threadlocal(wavs, workers=workers)
        except Exception as exc:
            print(f"[FAIL] workers={workers}: 예외 {type(exc).__name__}: {exc}")
            all_pass = False
            continue
        print(f"  parallel(workers={workers}) 소요: {t_par:.1f}s (speedup x{t_seq / max(t_par, 1e-6):.2f})")
        ok = compare(f"workers={workers}", baseline, candidate)
        if ok:
            print(f"  [PASS] workers={workers}: 결과 일치, 크래시 없음")
        else:
            all_pass = False

    print()
    if all_pass:
        print("=" * 50)
        print("모든 검증 통과. per-thread VAD 모델 방식 안전.")
        print("=" * 50)
        sys.exit(0)
    else:
        print("=" * 50)
        print("검증 실패. transcribe.py 반영 보류.")
        print("=" * 50)
        sys.exit(1)


if __name__ == "__main__":
    main()
