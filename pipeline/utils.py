"""공통 유틸리티: 로깅, 리트라이, 포맷팅"""

import functools
import logging
import os
import time
from logging.handlers import RotatingFileHandler


def setup_logging(log_dir: str, name: str = "pipeline") -> logging.Logger:
    os.makedirs(log_dir, exist_ok=True)
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    if not logger.handlers:
        # 파일 핸들러 (로테이팅, 10MB x 5)
        fh = RotatingFileHandler(
            os.path.join(log_dir, f"{name}.log"),
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        logger.addHandler(fh)

        # 콘솔 핸들러 (Windows에서 한국어 깨짐 방지)
        import sys
        import io
        stream = sys.stderr
        if sys.platform == "win32" and hasattr(stream, "buffer"):
            stream = io.TextIOWrapper(stream.buffer, encoding="utf-8", errors="replace")
        ch = logging.StreamHandler(stream)
        ch.setLevel(logging.INFO)
        ch.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%H:%M:%S",
        ))
        logger.addHandler(ch)

    return logger


def retry(max_retries: int = 3, backoff_base: float = 2.0, exceptions=(Exception,)):
    """지수 백오프 리트라이 데코레이터"""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exc = e
                    if attempt < max_retries:
                        delay = backoff_base ** attempt
                        logging.getLogger("pipeline").warning(
                            f"{func.__name__} 실패 (시도 {attempt + 1}/{max_retries + 1}): {e}. "
                            f"{delay:.1f}초 후 재시도..."
                        )
                        time.sleep(delay)
            raise last_exc
        return wrapper
    return decorator


def sec_to_hms(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{sec:02d}"


def format_size(size_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def format_duration(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h}시간 {m}분"
    return f"{m}분 {s}초"


def sanitize_filename(name: str, max_len: int = 80) -> str:
    """파일명에서 위험 문자 제거 및 길이 제한 (Windows MAX_PATH 방지)"""
    import re
    cleaned = re.sub(r'[\\/:\*\?"<>|\n]', '', name).strip()
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip()
    return cleaned
