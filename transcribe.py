import subprocess
import sys
import os
import math
import time
import re
import zlib
import warnings
import numpy as np
import wave
from collections import Counter

# B15: Windows cp949 콘솔 한글 깨짐 방지 (--help / 진행 로그)
from pipeline._io_encoding import force_utf8_stdio
force_utf8_stdio()

# 모든 경고 숨기기 (transformers 등의 사용자-비관심 경고)
warnings.filterwarnings("ignore")
os.environ["TRANSFORMERS_NO_ADVISORY_WARNINGS"] = "1"

# NOTE: 예전엔 `logging.disable(logging.WARNING)` 로 transformers INFO 를 뭉갰지만,
# 이 호출은 프로세스 전역이라 파이프라인의 pipeline 로거 INFO/WARNING 도 모두 삼켜버린다
# (증상: transcribe.py 를 import 한 순간부터 "자막 생성 시작" / log_func "[Whisper] ..."
# 로그가 완전히 사라지고, ERROR 로그만 남아서 실패 원인 추적이 불가능해짐).
# transformers 은 os.environ["TRANSFORMERS_VERBOSITY"] 로 억제한다.
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")

from split_video import find_bin, get_duration, FFMPEG, FFMPEG_DIR
from merge import merge_files

os.environ["PATH"] = FFMPEG_DIR + os.pathsep + os.environ.get("PATH", "")

SEGMENT_SECONDS = 3600  # 1시간
SAMPLE_RATE = 16000
WINDOW_SAMPLES = 30 * SAMPLE_RATE  # Whisper 30초 윈도우

# SRT 자막 품질 설정
MAX_CHARS_PER_LINE = 42       # 한 줄 최대 글자수 (넷플릭스 기준)
MAX_LINES = 2                 # 자막 최대 줄 수
MIN_SUBTITLE_SEC = 0.5        # 최소 자막 지속시간
MAX_SUBTITLE_SEC = 7.0        # 최대 자막 지속시간
MIN_GAP_SEC = 0.1             # 자막 간 최소 간격

# 환각 방지 설정
COMPRESSION_RATIO_THRESHOLD = 2.0  # 후처리 필터 (이 이상이면 환각으로 판단)

# 분할 파일명 패턴
PART_PATTERN = re.compile(
    r'Part\s+(\d+)\s+\((\d{2})-(\d{2})-(\d{2})\s+to\s+\d{2}-\d{2}-\d{2}\)'
)
PART_SUFFIX_PATTERN = re.compile(
    r'\s*-\s*Part\s+\d+\s+\(\d{2}-\d{2}-\d{2}\s+to\s+\d{2}-\d{2}-\d{2}\)'
)

# split_long_text() 에서 사용하는 사전 컴파일 패턴
SPLIT_PATTERNS = [
    re.compile(r'[.!?。~]\s*'),   # 문장 끝
    re.compile(r'[,、]\s*'),       # 쉼표
    re.compile(r'\s+'),            # 공백
]


def resolve_vad_prescan_workers(n_parts, configured_workers=None):
    """VAD prescan worker 수를 안전하게 결정한다.

    Windows + torch/silero 조합에서 공유 VAD 모델을 여러 스레드로 돌릴 때
    pythonw.exe access violation / heap corruption 이 보고되어, 기본값은 1
    (직렬)로 둔다. 필요 시 config/env 로만 명시적으로 늘린다.
    """
    if n_parts <= 0:
        return 1

    raw = os.environ.get("WHISPER_VAD_PRESCAN_WORKERS")
    if raw is not None:
        try:
            requested = int(raw)
        except ValueError:
            requested = 1
    elif configured_workers is not None:
        try:
            requested = int(configured_workers)
        except (TypeError, ValueError):
            requested = 1
    else:
        requested = 1

    if requested < 1:
        requested = 1
    return min(requested, n_parts)


# ──────────────────────────────────────────────
# 영상 분할 / 음성 추출
# ──────────────────────────────────────────────

def split_video(input_path, log_func=print):
    duration = get_duration(input_path)
    total_parts = math.ceil(duration / SEGMENT_SECONDS)
    name, ext = os.path.splitext(input_path)

    log_func(f"총 길이: {duration:.0f}초 ({duration/3600:.1f}시간)")
    log_func(f"분할 개수: {total_parts}개\n")

    part_paths = []
    for i in range(total_parts):
        start = i * SEGMENT_SECONDS
        output_path = f"{name}_part{i+1:03d}{ext}"
        part_paths.append(output_path)

        if os.path.isfile(output_path):
            log_func(f"[{i+1}/{total_parts}] 이미 존재: {output_path}")
            continue

        cmd = [
            FFMPEG, "-y",
            "-i", input_path,
            "-ss", str(start),
            "-t", str(SEGMENT_SECONDS),
            "-c", "copy",
            output_path,
        ]
        log_func(f"[{i+1}/{total_parts}] 분할 중: {output_path}")
        subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_ffmpeg_creationflags(),
        )

    return part_paths


def _ffmpeg_creationflags() -> int:
    """Windows 에서 ffmpeg subprocess 를 조용히 띄우기 위한 flag.

    `CREATE_NO_WINDOW` (0x08000000) 로 콘솔 subsystem 할당을 건너뛰면
    긴 VOD 를 여러 파트로 연속 처리할 때 발생하는 0xC0000142
    (STATUS_DLL_INIT_FAILED; "DLL init failed") 의 빈도를 줄일 수 있다.
    이 에러는 짧은 시간 내에 child 프로세스를 많이 띄우면 Windows
    desktop heap / csrss 자원 경합으로 간헐 발생.
    """
    if sys.platform != "win32":
        return 0
    return getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def extract_audio(video_path, log_func=print):
    audio_path = os.path.splitext(video_path)[0] + ".wav"

    # 헤더만 있고 샘플이 없는 파일(=이전 런이 중간에 죽으면서 남은 스텁)은
    # 재사용하지 말고 재추출한다. pcm_s16le 16kHz 모노는 1초만 해도 ~32KB.
    _WAV_MIN_BYTES = 1024
    if os.path.isfile(audio_path):
        try:
            size = os.path.getsize(audio_path)
        except OSError:
            size = 0
        if size >= _WAV_MIN_BYTES:
            log_func(f"  음성 이미 존재: {audio_path}")
            return audio_path
        log_func(f"  [경고] 기존 wav 가 너무 작음 ({size}B) → 재추출: {audio_path}")
        try:
            os.remove(audio_path)
        except OSError as e:
            log_func(f"  [경고] 기존 wav 삭제 실패 (무시): {e}")

    cmd = [
        FFMPEG, "-y",
        "-i", video_path,
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", str(SAMPLE_RATE),
        "-ac", "1",
        audio_path,
    ]
    log_func(f"  음성 추출 중: {audio_path}")

    # 0xC0000142 같은 Windows child-init 실패는 transient 한 경우가 많다.
    # 최대 3회, 점증 backoff 로 재시도. stderr 가 비어있으면 cmd 원문을 같이 기록.
    last_err: Exception | None = None
    for attempt in range(1, 4):
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                creationflags=_ffmpeg_creationflags(),
            )
        except OSError as e:
            last_err = e
            log_func(f"  [시도 {attempt}/3] subprocess.run OSError: {e}")
            time.sleep(2 * attempt)
            continue

        if result.returncode == 0:
            # ffmpeg 가 성공 코드를 반환해도 실제로 거의 비어있는 파일을
            # 남기는 경우가 있다(중단/파이프 이슈). 크기를 검증해 스텁이면 실패로 취급.
            try:
                out_size = os.path.getsize(audio_path)
            except OSError:
                out_size = 0
            if out_size < 1024:
                log_func(
                    f"  [시도 {attempt}/3] ffmpeg 성공 코드지만 결과물이 비어있음 "
                    f"({out_size}B) → 재시도"
                )
                last_err = RuntimeError(
                    f"ffmpeg 결과물 스텁: {os.path.basename(audio_path)} ({out_size}B)"
                )
                try:
                    os.remove(audio_path)
                except OSError:
                    pass
                if attempt < 3:
                    time.sleep(2 * attempt)
                    continue
                break
            if attempt > 1:
                log_func(f"  음성 추출 성공 (재시도 {attempt} 회 만에)")
            return audio_path

        stderr_tail = result.stderr.decode("utf-8", errors="replace")[-400:]
        log_func(
            f"  [시도 {attempt}/3] ffmpeg returncode={result.returncode} "
            f"(0x{result.returncode & 0xFFFFFFFF:08X}) "
            f"stderr_empty={not stderr_tail.strip()}"
        )
        last_err = RuntimeError(
            f"ffmpeg 음성 추출 실패 (returncode={result.returncode}): "
            f"{os.path.basename(video_path)}\n"
            f"cmd={cmd}\n"
            f"stderr_tail={stderr_tail}"
        )
        # transient Windows child-init 실패면 backoff 후 재시도.
        # returncode 를 signed int 로 해석하면 0xC0000142 = -1073741502 등.
        is_windows_init_fail = (
            sys.platform == "win32"
            and result.returncode in (
                -1073741502,  # 0xC0000142 DLL_INIT_FAILED
                -1073741510,  # 0xC000013A CONTROL_C_EXIT
                3221225794,   # 0xC0000142 unsigned
                1073807364,   # 0x40010004 DBG_CONTROL_C
            )
        )
        if attempt < 3 and (is_windows_init_fail or not stderr_tail.strip()):
            time.sleep(2 * attempt)
            continue
        break

    assert last_err is not None
    raise last_err


# ──────────────────────────────────────────────
# 모델 로드 (Whisper + Silero VAD)
# ──────────────────────────────────────────────

def load_models(log_func=print):
    import torch
    from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor

    model_id = "openai/whisper-large-v3-turbo"
    device = "cuda" if torch.cuda.is_available() else "cpu"
    torch_dtype = torch.float16 if device == "cuda" else torch.float32

    log_func(f"\nWhisper 로드 중: {model_id} (device={device})")
    model = AutoModelForSpeechSeq2Seq.from_pretrained(
        model_id,
        torch_dtype=torch_dtype,
        low_cpu_mem_usage=True,
    )
    model.to(device)
    processor = AutoProcessor.from_pretrained(model_id)
    log_func("Whisper 로드 완료!")

    # Silero VAD 로드 (CPU 유지: 작은 모델이라 GPU 커널 런치 오버헤드가 더 크다)
    log_func("Silero VAD 로드 중...")
    vad_model, vad_utils = torch.hub.load(
        repo_or_dir="snakers4/silero-vad",
        model="silero_vad",
        force_reload=False,
    )
    log_func("Silero VAD 로드 완료!\n")

    return model, processor, device, torch_dtype, vad_model, vad_utils


# ──────────────────────────────────────────────
# 유틸리티
# ──────────────────────────────────────────────

def format_timestamp(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def load_audio(audio_path):
    with wave.open(audio_path, "rb") as wf:
        frames = wf.readframes(wf.getnframes())
        audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    if len(audio) == 0:
        raise ValueError(f"오디오 파일이 비어 있습니다: {audio_path}")
    return audio


def compression_ratio(text):
    """텍스트의 zlib 압축률. 높을수록 반복적(환각 가능성)."""
    text_bytes = text.encode("utf-8")
    return len(text_bytes) / len(zlib.compress(text_bytes))


def is_hallucination(text):
    """환각 여부를 종합 판단한다."""
    text = text.strip()
    if not text:
        return True

    # 1) 압축률 기반 (반복 텍스트 감지)
    if len(text) > 10 and compression_ratio(text) > COMPRESSION_RATIO_THRESHOLD:
        return True

    # 2) 동일 문구 반복 감지 (예: "팔찌랑 벨트? 팔찌랑 벨트? 팔찌랑 벨트?")
    words = text.split()
    if len(words) >= 6:
        # 2~5어절 n-gram 반복 체크
        for n in range(2, min(6, len(words) // 2 + 1)):
            ngrams = [" ".join(words[i:i+n]) for i in range(len(words) - n + 1)]
            counts = Counter(ngrams)
            if counts.most_common(1)[0][1] >= 3:  # 같은 n-gram이 3회 이상 반복
                return True

    # 3) 짧은 텍스트가 반복되는 패턴 (예: "아 아 아 아 아")
    if len(set(words)) == 1 and len(words) >= 3:
        return True

    return False


# ──────────────────────────────────────────────
# VAD: 음성 구간 탐지
# ──────────────────────────────────────────────

def get_speech_segments(audio, vad_model, vad_utils):
    """Silero VAD로 음성 구간만 추출한다. [(start_sample, end_sample), ...]"""
    import torch

    get_speech_timestamps = vad_utils[0]
    audio_tensor = torch.from_numpy(audio).float()

    speech_timestamps = get_speech_timestamps(
        audio_tensor,
        vad_model,
        sampling_rate=SAMPLE_RATE,
        threshold=0.5,
        min_speech_duration_ms=250,     # 최소 음성 길이 250ms
        min_silence_duration_ms=500,    # 0.5초 이상 무음이면 분리 (자막 단위 세분화)
        speech_pad_ms=300,              # 음성 앞뒤 300ms 패딩 (잘림 방지)
    )

    segments = []
    for ts in speech_timestamps:
        segments.append((ts["start"], ts["end"]))

    return segments


def merge_vad_into_chunks(speech_segments, total_samples, max_chunk_sec=10):
    """VAD 결과를 최대 10초 이하의 chunk로 묶는다. 자막 단위를 작게 유지."""
    max_samples = max_chunk_sec * SAMPLE_RATE
    chunks = []
    current_start = None
    current_end = None

    for seg_start, seg_end in speech_segments:
        if current_start is None:
            current_start = seg_start
            current_end = seg_end
            continue

        if seg_end - current_start > max_samples:
            chunks.append((current_start, current_end))
            current_start = seg_start
            current_end = seg_end
        else:
            current_end = seg_end

    if current_start is not None:
        chunks.append((current_start, current_end))

    return chunks


# ──────────────────────────────────────────────
# Whisper 디코딩 결과 파싱
# ──────────────────────────────────────────────

def parse_whisper_tokens(decoded_text):
    """Whisper 출력에서 timestamp 토큰을 파싱한다.
    반환: (segments, last_timestamp)"""
    segments = []
    last_ts = 0.0

    pattern = r"<\|(\d+\.\d+)\|>(.*?)<\|(\d+\.\d+)\|>"
    matches = re.findall(pattern, decoded_text)

    for start_str, text, end_str in matches:
        text = text.strip()
        if not text:
            continue
        start = float(start_str)
        end = float(end_str)
        if end <= start:  # 역방향/동일 타임스탬프 필터
            continue
        segments.append({"start": start, "end": end, "text": text})
        last_ts = max(last_ts, end)

    if not segments:
        clean = re.sub(r"<\|.*?\|>", "", decoded_text).strip()
        if clean:
            segments.append({"start": 0, "end": 30, "text": clean})
            last_ts = 30

    all_ts = re.findall(r"<\|(\d+\.\d+)\|>", decoded_text)
    if all_ts:
        last_ts = max(last_ts, max(float(t) for t in all_ts))

    return segments, last_ts


# ──────────────────────────────────────────────
# SRT 후처리 (자막 품질 개선)
# ──────────────────────────────────────────────

def split_long_text(text, start, end):
    """긴 텍스트를 문장 부호 기준으로 분할한다."""
    duration = end - start
    if duration <= MAX_SUBTITLE_SEC and len(text) <= MAX_CHARS_PER_LINE * MAX_LINES:
        return [{"start": start, "end": end, "text": text}]

    parts = []
    remaining_text = text
    remaining_start = start
    remaining_end = end

    while len(remaining_text) > MAX_CHARS_PER_LINE and (remaining_end - remaining_start) > MAX_SUBTITLE_SEC:
        best_pos = -1
        target = len(remaining_text) // 2

        for pattern in SPLIT_PATTERNS:
            # 텍스트 중간 부근에서 분할점 찾기
            for match in pattern.finditer(remaining_text):
                pos = match.end()
                if pos < 5 or pos > len(remaining_text) - 5:
                    continue
                if best_pos == -1 or abs(pos - target) < abs(best_pos - target):
                    best_pos = pos
            if best_pos != -1:
                break

        if best_pos == -1:
            break

        # 시간을 글자 비율로 배분
        ratio = best_pos / len(remaining_text)
        split_time = remaining_start + (remaining_end - remaining_start) * ratio

        parts.append({
            "start": remaining_start,
            "end": split_time,
            "text": remaining_text[:best_pos].strip(),
        })
        remaining_text = remaining_text[best_pos:].strip()
        remaining_start = split_time

    if remaining_text:
        parts.append({
            "start": remaining_start,
            "end": remaining_end,
            "text": remaining_text,
        })

    return parts


def postprocess_entries(entries):
    """자막 엔트리를 후처리하여 품질을 높인다."""
    if not entries:
        return entries

    result = []

    for entry in entries:
        text = entry["text"].strip()
        start = entry["start"]
        end = entry["end"]
        duration = end - start

        # 1) 너무 짧은 자막 건너뛰기
        if duration < MIN_SUBTITLE_SEC:
            continue

        # 2) 긴 자막을 문장 부호 기준으로 분할
        parts = split_long_text(text, start, end)
        result.extend(parts)

    # 3) 짧은 인접 자막 병합 (같은 문장이 쪼개진 경우)
    merged = []
    for entry in result:
        if merged and entry["start"] - merged[-1]["end"] < MIN_GAP_SEC:
            prev = merged[-1]
            combined = prev["text"] + " " + entry["text"]
            combined_dur = entry["end"] - prev["start"]
            if combined_dur <= MAX_SUBTITLE_SEC and len(combined) <= MAX_CHARS_PER_LINE * MAX_LINES:
                prev["end"] = entry["end"]
                prev["text"] = combined
                continue
        merged.append(dict(entry))

    # 4) 타임스탬프 간격 보정 (겹침 제거)
    for i in range(1, len(merged)):
        if merged[i]["start"] < merged[i-1]["end"]:
            merged[i-1]["end"] = merged[i]["start"] - 0.001

    return merged


# ──────────────────────────────────────────────
# 자막 생성 (핵심)
# ──────────────────────────────────────────────

def transcribe_audio(
    model, processor, device, torch_dtype,
    vad_model, vad_utils,
    audio_path,
    time_offset=0, part_num=0, total_parts=0,
    log_func=print,
    progress_func=None,
    chunk_offset=0,
    total_chunks_global=0,
    precomputed_speech_segments=None,
    preloaded_audio=None,
    stop_event=None,
    initial_prompt_text: str | None = None,
):
    """
    반환: (entries, total_chunks_in_this_part)
    preloaded_audio: VAD prescan 시 이미 로드한 ndarray → 재로드 생략
    stop_event: threading.Event — set() 시 루프 중단 후 부분 결과 반환
    """
    import torch

    log_func(f"\n  [{part_num}/{total_parts}] 자막 생성 중: {audio_path}")
    log_func(f"  시간 오프셋: {format_timestamp(time_offset)}")
    t_start = time.time()

    audio = preloaded_audio if preloaded_audio is not None else load_audio(audio_path)
    total_samples = len(audio)
    total_duration = total_samples / SAMPLE_RATE

    # 1) Silero VAD로 음성 구간 탐지
    if precomputed_speech_segments is not None:
        speech_segments = precomputed_speech_segments
        log_func("  VAD 결과 재사용 (사전 분석)")
    else:
        log_func(f"  VAD 분석 중... (총 {total_duration:.0f}초)")
        speech_segments = get_speech_segments(audio, vad_model, vad_utils)

    speech_duration = sum(e - s for s, e in speech_segments) / SAMPLE_RATE
    if total_duration > 0:
        log_func(f"  음성 구간: {speech_duration:.0f}초 / {total_duration:.0f}초 ({speech_duration/total_duration*100:.0f}%)")
    else:
        log_func(f"  음성 구간: {speech_duration:.0f}초")

    if not speech_segments:
        log_func("  음성 없음, 건너뜀")
        return [], 0

    # 2) VAD 구간을 Whisper 윈도우 크기로 묶기
    chunks = merge_vad_into_chunks(speech_segments, total_samples)
    total_chunks = len(chunks)

    entries = []
    count = 0

    # initial_prompt: 한국어 구두점/스타일 가이드 + (옵션) 스트리머별 고유명사 bias.
    # Whisper prompt_ids 는 약 224 토큰 상한. 초과 시 processor 가 자르는데
    # 우리는 lexicon 에서 이미 limit 로 컨트롤하므로 그대로 넘긴다.
    _prompt_text = initial_prompt_text or (
        "안녕하세요, 환영합니다. 오늘도 재밌게 해봅시다! 자, 그러면 시작할게요."
    )
    prompt_ids = processor.get_prompt_ids(
        _prompt_text,
        return_tensors="pt",
    ).to(device)

    # batch_size: b32 실험 결과 bs=4 에서 1.29x 속도 + 품질 유지(jaccard 0.98)
    # peak VRAM ~2.5GB (RTX 2070 Super 8GB 기준 안전). env 로 override 가능.
    batch_size = int(os.environ.get("WHISPER_BATCH_SIZE", "4")) if device == "cuda" else 1
    if batch_size < 1:
        batch_size = 1

    for bi in range(0, len(chunks), batch_size):
        if stop_event is not None and stop_event.is_set():
            log_func("  [취소] 처리 중단됨")
            break

        batch = chunks[bi:bi + batch_size]
        chunk_audios = [audio[s:e] for s, e in batch]
        chunk_start_secs = [s / SAMPLE_RATE for s, _ in batch]

        inputs = processor(chunk_audios, sampling_rate=SAMPLE_RATE, return_tensors="pt")
        input_features = inputs.input_features.to(device, dtype=torch_dtype)

        with torch.no_grad():
            predicted_ids = model.generate(
                input_features,
                language="ko",
                task="transcribe",
                return_timestamps=True,
                prompt_ids=prompt_ids,
                # ── 환각 방지 ──
                condition_on_prev_tokens=False,
                compression_ratio_threshold=1.35,
                no_speech_threshold=0.6,
                logprob_threshold=-1.0,
                temperature=(0.0, 0.2, 0.4, 0.6, 0.8, 1.0),
                # ── 품질 향상 ──
                num_beams=5,                  # 빔 서치 (정확도 향상)
                no_repeat_ngram_size=3,       # 3-gram 반복 차단
                repetition_penalty=1.2,       # 반복 페널티
                length_penalty=1.0,
            )

        decoded_all = processor.batch_decode(predicted_ids, skip_special_tokens=False)

        for bj, (decoded, chunk_start_sec) in enumerate(zip(decoded_all, chunk_start_secs)):
            ci = bi + bj
            segments, _ = parse_whisper_tokens(decoded)

            for seg in segments:
                # 환각 필터링
                if is_hallucination(seg["text"]):
                    log_func(f"    [환각 필터] {seg['text'][:50]}...")
                    continue

                count += 1
                abs_start = seg["start"] + chunk_start_sec + time_offset
                abs_end = seg["end"] + chunk_start_sec + time_offset
                entries.append({"start": abs_start, "end": abs_end, "text": seg["text"]})
                log_func(f"    #{count} [{format_timestamp(abs_start)} --> {format_timestamp(abs_end)}] {seg['text']}")

            # 진행률 (배치 마지막 청크 기준)
            elapsed = time.time() - t_start
            current_chunk = chunk_offset + ci + 1
            effective_total = total_chunks_global if total_chunks_global > 0 else total_chunks
            progress_pct = (current_chunk / effective_total * 100) if effective_total > 0 else 0
            log_func(f"    -- chunk {ci+1}/{total_chunks} ({progress_pct:.0f}%) | {elapsed:.0f}초 경과")

            if progress_func is not None:
                progress_func(current_chunk, effective_total)

    elapsed = time.time() - t_start
    log_func(f"  완료: {len(entries)}개 자막 ({elapsed:.1f}초 소요)")

    if device == "cuda":
        try:
            torch.cuda.empty_cache()
        except Exception:
            pass

    return entries, total_chunks


# ──────────────────────────────────────────────
# SRT 저장
# ──────────────────────────────────────────────

def write_srt(entries, output_path):
    with open(output_path, "w", encoding="utf-8") as f:
        for i, entry in enumerate(entries, 1):
            f.write(f"{i}\n")
            f.write(f"{format_timestamp(entry['start'])} --> {format_timestamp(entry['end'])}\n")
            f.write(f"{entry['text']}\n\n")


# ──────────────────────────────────────────────
# 분할 파일명 파싱 유틸리티
# ──────────────────────────────────────────────

def parse_time_offset_from_filename(filepath):
    """
    "Part 2 (01-00-01 to 02-00-03).mp3" → (part_num=2, offset=3601.0)
    패턴 불일치 → (None, None)
    """
    m = PART_PATTERN.search(os.path.basename(filepath))
    if not m:
        return None, None
    part_num = int(m.group(1))
    h, mn, s = int(m.group(2)), int(m.group(3)), int(m.group(4))
    return part_num, float(h * 3600 + mn * 60 + s)


def build_files_info_split(file_paths):
    """
    파일 목록 → [{"path": str, "time_offset": float, "part_num": int, "total_parts": int}, ...]
    - 파일명 파싱 성공: Part 번호 순 정렬 + 파싱된 offset 사용
    - 파싱 실패: 파일 순서대로 0, SEGMENT_SECONDS, 2*SEGMENT_SECONDS ... 할당
    """
    parsed = []
    all_parseable = True
    for fp in file_paths:
        part_num, offset = parse_time_offset_from_filename(fp)
        if part_num is None:
            all_parseable = False
        parsed.append((fp, part_num, offset))

    total = len(file_paths)
    results = []

    if all_parseable:
        parsed.sort(key=lambda x: x[1])
        for fp, part_num, offset in parsed:
            results.append({
                "path": fp,
                "time_offset": offset,
                "part_num": part_num,
                "total_parts": total,
            })
    else:
        for i, (fp, _, _) in enumerate(parsed):
            results.append({
                "path": fp,
                "time_offset": i * SEGMENT_SECONDS,
                "part_num": i + 1,
                "total_parts": total,
            })

    return results


def determine_srt_output(original_input: str) -> str:
    """원본 파일 경로의 확장자를 .srt로 변경한다."""
    return os.path.splitext(original_input)[0] + ".srt"


def _get_merge_output_path(files_info: list) -> str:
    """
    분할 파일 목록으로부터 병합 출력 경로를 결정한다.

    - Part 패턴이 있으면 제거한 깔끔한 이름 사용
      ex) "[옵시온] 도태의 왕 - Part 1 (00-00-00 to 01-00-01).mp3"
          → "[옵시온] 도태의 왕.mp3"

    - Part 패턴이 없으면 (예: 1.mp4, 2.mp4 ...) _merged 접미사 추가
      ex) "1.mp4" → "1_merged.mp4"
      (입력 파일 자체와 경로가 겹치는 것을 방지)
    """
    first_path = files_info[0]["path"]
    _, ext = os.path.splitext(first_path)
    name = os.path.splitext(os.path.basename(first_path))[0]

    stripped = PART_SUFFIX_PATTERN.sub("", name).strip()
    if stripped != name:
        # Part 패턴이 제거된 경우 → 깔끔한 이름 사용
        name = stripped
    else:
        # Part 패턴 없음 → _merged 접미사로 입력 파일과 충돌 방지
        name = name + "_merged"

    output_dir = os.path.dirname(os.path.abspath(first_path))
    return os.path.join(output_dir, name + ext)


# ──────────────────────────────────────────────
# 메인 엔트리 포인트
# ──────────────────────────────────────────────

def run_caption_generation(
    files_info,
    is_split,
    log_func=print,
    progress_func=None,
    cleanup=False,
    stop_event=None,
    initial_prompt_text: str | None = None,
    vad_prescan_workers: int | None = None,
):
    """
    files_info: [{"path": str, ...}, ...]
    is_split=False: files_info[0] 단일 파일 → 1시간 단위 분할 후 처리
    is_split=True:  분할 파일 목록 → 손실 없이 병합 → 동일 파이프라인으로 처리

    진행률 2패스 방식:
      1. VAD 선행 스캔 → total_chunks_global 계산 (오디오 캐싱으로 이중 로드 방지)
      2. transcribe_audio에 precomputed_speech_segments + preloaded_audio 전달

    cleanup=True: SRT 저장 후 중간 생성 파일(분할 파트, WAV, 병합 파일) 자동 삭제
    stop_event: threading.Event — set() 시 다음 청크에서 중단 후 부분 SRT 저장

    반환: SRT 파일 경로 (str)
    """
    temp_files = []  # 완료 후 삭제할 임시 파일 목록

    # ── 0단계: 분할 파일이면 먼저 병합 ──────────────────────
    if is_split:
        log_func("=" * 50)
        log_func("0단계: 분할 파일 병합")
        log_func("=" * 50)

        merged_path = _get_merge_output_path(files_info)
        input_abspaths = {os.path.abspath(fi["path"]) for fi in files_info}

        already_merged = (
            os.path.isfile(merged_path)
            and os.path.abspath(merged_path) not in input_abspaths
        )

        if already_merged:
            log_func(f"이미 병합된 파일 존재, 재사용: {os.path.basename(merged_path)}")
        else:
            file_paths = [fi["path"] for fi in files_info]
            merge_files(file_paths, merged_path, log_func)

        temp_files.append(merged_path)  # 병합 파일은 임시 파일
        # 이후 단일 파일 파이프라인과 동일하게 처리
        original_input = merged_path
    else:
        original_input = files_info[0]["path"]

    # ── 1단계: 1시간 단위 분할 ──────────────────────────────
    log_func("\n" + "=" * 50)
    log_func("1단계: 영상/음성 분할")
    log_func("=" * 50)
    part_paths = split_video(original_input, log_func)
    temp_files.extend(part_paths)  # 분할 파트는 임시 파일

    # ── 2단계: 음성 추출 ────────────────────────────────────
    log_func("\n" + "=" * 50)
    log_func("2단계: 음성 추출")
    log_func("=" * 50)
    audio_infos = []
    for i, part_path in enumerate(part_paths):
        audio_path = extract_audio(part_path, log_func)
        temp_files.append(audio_path)  # 추출된 WAV는 임시 파일
        audio_infos.append({
            "audio_path": audio_path,
            "time_offset": i * SEGMENT_SECONDS,
            "part_num": i + 1,
            "total_parts": len(part_paths),
        })

    # ── 3단계: 모델 로드 (Whisper + VAD) ───────────────────
    log_func("\n" + "=" * 50)
    log_func("3단계: 모델 로드 (Whisper + Silero VAD)")
    log_func("=" * 50)
    model, processor, device, torch_dtype, vad_model, vad_utils = load_models(log_func)

    # ── VAD 사전 스캔: total_chunks_global 계산 (오디오 캐싱) ──
    # 병렬화 정책:
    #   - Silero VAD 의 get_speech_timestamps 는 model.reset_states() 등으로
    #     모델 내부 버퍼를 mutate 하므로, 단일 모델 인스턴스를 여러 스레드에서
    #     공유하면 heap corruption (0xc0000374) 이 발생한다.
    #   - 안전 전략: 스레드마다 자기 VAD 모델 인스턴스를 보유하도록
    #     threading.local() 에 지연 로딩한다. Silero 는 ~1MB 라 복제 비용 무시 가능.
    #   - 검증 내역: experiments/test_vad_prescan_threadlocal.py
    #     (workers=2 에서 x1.98, workers=4 에서 x3.13, segments 완전 일치)
    n_parts = len(audio_infos)
    vad_workers = resolve_vad_prescan_workers(
        n_parts,
        configured_workers=vad_prescan_workers,
    )
    if vad_workers == 1:
        log_func("\nVAD 사전 분석 중 (안전 모드, workers=1)...")
    else:
        log_func(f"\nVAD 사전 분석 중 (병렬, workers={vad_workers}, per-thread VAD 모델)...")

    all_precomputed_segments = [None] * n_parts
    all_preloaded_audios = [None] * n_parts
    all_chunk_counts = [0] * n_parts

    if vad_workers == 1:
        for i, afi in enumerate(audio_infos):
            audio = load_audio(afi["audio_path"])
            speech_segs = get_speech_segments(audio, vad_model, vad_utils)
            chunks = merge_vad_into_chunks(speech_segs, len(audio))
            all_precomputed_segments[i] = speech_segs
            all_preloaded_audios[i] = audio
            all_chunk_counts[i] = len(chunks)
            log_func(
                f"  [{i + 1}/{n_parts}] {os.path.basename(audio_infos[i]['audio_path'])}: "
                f"{len(chunks)}개 청크"
            )
    else:
        import threading
        from concurrent.futures import ThreadPoolExecutor, as_completed

        # 각 워커 스레드가 자기 VAD 인스턴스를 갖게 하여 모델 내부 버퍼 충돌을 원천 차단.
        tlocal = threading.local()

        def _get_thread_vad():
            m = getattr(tlocal, "model", None)
            if m is None:
                import torch

                tlocal.model, tlocal.utils = torch.hub.load(
                    repo_or_dir="snakers4/silero-vad",
                    model="silero_vad",
                    force_reload=False,
                    trust_repo=True,
                    verbose=False,
                )
            return tlocal.model, tlocal.utils

        def _prescan_one_threadlocal(afi):
            local_vad, local_utils = _get_thread_vad()
            audio = load_audio(afi["audio_path"])
            speech_segs = get_speech_segments(audio, local_vad, local_utils)
            chunks = merge_vad_into_chunks(speech_segs, len(audio))
            return audio, speech_segs, len(chunks)

        with ThreadPoolExecutor(max_workers=vad_workers) as pool:
            futures = {
                pool.submit(_prescan_one_threadlocal, afi): i
                for i, afi in enumerate(audio_infos)
            }
            done_count = 0
            for fut in as_completed(futures):
                i = futures[fut]
                audio, speech_segs, n_chunks = fut.result()
                all_precomputed_segments[i] = speech_segs
                all_preloaded_audios[i] = audio
                all_chunk_counts[i] = n_chunks
                done_count += 1
                log_func(
                    f"  [{done_count}/{n_parts}] {os.path.basename(audio_infos[i]['audio_path'])}: "
                    f"{n_chunks}개 청크"
                )

    total_chunks_global = sum(all_chunk_counts)
    log_func(f"총 청크 수: {total_chunks_global}")

    # ── 4단계: 자막 생성 ────────────────────────────────────
    log_func("\n" + "=" * 50)
    log_func("4단계: 자막 생성")
    log_func("=" * 50)
    all_entries = []
    chunk_offset = 0
    total_start = time.time()

    for i, (afi, precomp_segs, preloaded) in enumerate(
        zip(audio_infos, all_precomputed_segments, all_preloaded_audios)
    ):
        if stop_event is not None and stop_event.is_set():
            log_func("[취소] 파트 처리 중단됨")
            break

        entries, part_chunks = transcribe_audio(
            model, processor, device, torch_dtype, vad_model, vad_utils,
            afi["audio_path"],
            time_offset=afi["time_offset"],
            part_num=afi["part_num"],
            total_parts=afi["total_parts"],
            log_func=log_func,
            progress_func=progress_func,
            chunk_offset=chunk_offset,
            total_chunks_global=total_chunks_global,
            precomputed_speech_segments=precomp_segs,
            preloaded_audio=preloaded,
            stop_event=stop_event,
            initial_prompt_text=initial_prompt_text,
        )
        all_entries.extend(entries)
        chunk_offset += part_chunks

        elapsed_total = time.time() - total_start
        if i + 1 < len(audio_infos):
            avg_per_part = elapsed_total / (i + 1)
            remaining = avg_per_part * (len(audio_infos) - i - 1)
            log_func(
                f"  전체 진행: {i+1}/{len(audio_infos)} | "
                f"경과: {elapsed_total:.0f}초 | "
                f"예상 남은 시간: {remaining:.0f}초"
            )

    # ── 5단계: 후처리 ───────────────────────────────────────
    log_func("\n" + "=" * 50)
    log_func("5단계: 자막 후처리")
    log_func("=" * 50)
    before_count = len(all_entries)
    all_entries = postprocess_entries(all_entries)
    log_func(f"후처리 완료: {before_count}개 → {len(all_entries)}개")

    # ── 6단계: SRT 저장 ─────────────────────────────────────
    log_func("\n" + "=" * 50)
    log_func("6단계: SRT 파일 저장")
    log_func("=" * 50)
    srt_output = determine_srt_output(original_input)
    write_srt(all_entries, srt_output)
    log_func(f"저장 완료: {srt_output} (총 {len(all_entries)}개 자막)")

    # ── 7단계: 임시 파일 정리 (cleanup=True 일 때만) ────────
    if cleanup:
        log_func("\n" + "=" * 50)
        log_func("7단계: 임시 파일 정리")
        log_func("=" * 50)
        deleted, failed = 0, 0
        for fp in temp_files:
            if os.path.isfile(fp):
                try:
                    os.remove(fp)
                    log_func(f"삭제: {os.path.basename(fp)}")
                    deleted += 1
                except Exception as e:
                    log_func(f"삭제 실패: {os.path.basename(fp)} ({e})")
                    failed += 1
        log_func(f"정리 완료: {deleted}개 삭제" + (f", {failed}개 실패" if failed else ""))

    return srt_output


# ──────────────────────────────────────────────
# CLI 엔트리 포인트
# ──────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(
        prog="transcribe.py",
        description="Whisper 기반 한국어 자막 자동 생성기",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=(
            "예시:\n"
            "  통 영상/MP3:       python transcribe.py video.mp4\n"
            "                     python transcribe.py audio.mp3\n"
            "  분할된 영상/MP3:   python transcribe.py --split part1.mp3 part2.mp3 part3.mp3\n"
        ),
    )
    parser.add_argument(
        "files",
        nargs="+",
        metavar="FILE",
        help="입력 파일. 통 파일은 1개, 분할 파일은 여러 개 지정",
    )
    parser.add_argument(
        "--split",
        action="store_true",
        help="분할 파일 모드: 여러 파트 파일을 순서대로 처리 (파일명에서 시간 오프셋 자동 파싱)",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="완료 후 분할 파트, WAV, 병합 파일 등 중간 생성 파일 자동 삭제",
    )

    args = parser.parse_args()

    # 파일 존재 확인
    for f in args.files:
        if not os.path.isfile(f):
            print(f"파일을 찾을 수 없습니다: {f}")
            sys.exit(1)

    if args.split:
        files_info = build_files_info_split(args.files)
        print(f"분할 파일 모드: {len(files_info)}개 파일")
        for fi in files_info:
            print(f"  Part {fi['part_num']}: {fi['path']} (offset={fi['time_offset']:.0f}s)")
        print()
        run_caption_generation(files_info, is_split=True, cleanup=args.cleanup)
    else:
        if len(args.files) > 1:
            print("오류: 통 파일 모드에서는 파일을 1개만 지정하세요. 여러 파일은 --split 옵션을 사용하세요.")
            sys.exit(1)
        files_info = [{"path": args.files[0], "time_offset": 0.0, "part_num": 1, "total_parts": 1}]
        run_caption_generation(files_info, is_split=False, cleanup=args.cleanup)


if __name__ == "__main__":
    main()
