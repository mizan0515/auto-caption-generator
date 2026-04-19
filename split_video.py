import subprocess
import sys
import os
import math
import shutil

FFMPEG_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA", ""),
    r"Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.0.1-full_build\bin",
)


def find_bin(name):
    """PATH 또는 winget 설치 경로에서 실행파일을 찾는다."""
    found = shutil.which(name)
    if found:
        return found
    candidate = os.path.join(FFMPEG_DIR, f"{name}.exe")
    if os.path.isfile(candidate):
        return candidate
    print(f"{name}을(를) 찾을 수 없습니다. ffmpeg를 설치해주세요.")
    sys.exit(1)


FFPROBE = find_bin("ffprobe")
FFMPEG = find_bin("ffmpeg")


def _creationflags() -> int:
    """Windows: CREATE_NO_WINDOW 로 ffmpeg/ffprobe 를 조용히 띄운다.

    긴 VOD 를 다수 파트로 빠르게 연속 처리할 때 Windows 가 child 프로세스
    콘솔 subsystem 초기화를 거부하며 0xC0000142 를 내는 경우가 있어
    예방적으로 적용.
    """
    if sys.platform != "win32":
        return 0
    return getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def get_duration(input_path):
    """Return media duration in seconds via ffprobe."""
    result = subprocess.run(
        [
            FFPROBE, "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            input_path,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=_creationflags(),
    )
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        detail = stderr or stdout or "(ffprobe output unavailable)"
        raise RuntimeError(
            f"ffprobe failed (returncode={result.returncode}):\n{detail}\ninput={input_path}"
        )

    stdout = (result.stdout or "").strip()
    if not stdout:
        raise RuntimeError(f"ffprobe returned empty duration: {input_path}")

    try:
        duration = float(stdout)
    except ValueError as exc:
        raise RuntimeError(
            f"ffprobe returned non-numeric duration: {stdout!r} ({input_path})"
        ) from exc

    if duration <= 0:
        raise RuntimeError(f"invalid media duration: {duration} ({input_path})")
    return duration

def split_video(input_path, segment_seconds=3600):
    if not os.path.isfile(input_path):
        print(f"파일을 찾을 수 없습니다: {input_path}")
        sys.exit(1)

    duration = get_duration(input_path)
    total_parts = math.ceil(duration / segment_seconds)
    name, ext = os.path.splitext(input_path)

    print(f"총 길이: {duration:.0f}초 ({duration/3600:.1f}시간)")
    print(f"분할 개수: {total_parts}개\n")

    for i in range(total_parts):
        start = i * segment_seconds
        output_path = f"{name}_part{i+1:03d}{ext}"
        cmd = [
            FFMPEG, "-y",
            "-i", input_path,
            "-ss", str(start),
            "-t", str(segment_seconds),
            "-c", "copy",
            output_path,
        ]
        print(f"[{i+1}/{total_parts}] {output_path}")
        result = subprocess.run(
            cmd, capture_output=True, creationflags=_creationflags()
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"ffmpeg 분할 실패 [{i+1}/{total_parts}] (returncode={result.returncode})"
            )

    print("\n완료!")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"사용법: python {sys.argv[0]} <영상파일.mp4>")
        sys.exit(1)

    split_video(sys.argv[1])
