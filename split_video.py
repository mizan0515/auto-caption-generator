import subprocess
import sys
import os
import math
import shutil

FFMPEG_DIR = os.path.join(
    os.environ["LOCALAPPDATA"],
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


def get_duration(input_path):
    """ffprobe로 영상 총 길이(초)를 가져온다."""
    result = subprocess.run(
        [
            FFPROBE, "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            input_path,
        ],
        capture_output=True, text=True,
    )
    return float(result.stdout.strip())


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
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    print("\n완료!")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"사용법: python {sys.argv[0]} <영상파일.mp4>")
        sys.exit(1)

    split_video(sys.argv[1])
