"""헤드리스 Whisper 자막 생성 래퍼"""

import logging
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

logger = logging.getLogger("pipeline")


def transcribe_video(video_path: str, progress_func=None) -> str:
    """
    비디오 파일을 Whisper로 전사하여 SRT 파일 생성.
    기존 transcribe.py의 run_caption_generation()을 직접 호출.
    반환: SRT 파일 경로
    """
    from transcribe import run_caption_generation

    logger.info(f"자막 생성 시작: {video_path}")

    def log_func(msg):
        logger.info(f"  [Whisper] {msg}")

    def prog_func(current, total):
        if progress_func:
            progress_func(current, total)
        if current % 10 == 0 or current == total:
            logger.info(f"  [Whisper] 진행: {current}/{total} 청크")

    files_info = [{
        "path": video_path,
        "time_offset": 0.0,
        "part_num": 1,
        "total_parts": 1,
    }]

    srt_path = run_caption_generation(
        files_info=files_info,
        is_split=False,
        log_func=log_func,
        progress_func=prog_func,
    )

    logger.info(f"자막 생성 완료: {srt_path}")
    return srt_path
