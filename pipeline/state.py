"""파이프라인 처리 상태 영속화 (스레드 잠금 + 파일 잠금 포함)"""

import json
import os
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

KST = timezone(timedelta(hours=9))


class PipelineState:
    """
    스레드 안전한 상태 관리.
    - _lock: 인-프로세스 스레드 간 동시 접근 방지
    - 원자적 파일 쓰기: tmp → replace
    """

    def __init__(self, state_path: str):
        self._path = state_path
        self._lock = threading.Lock()
        self._data = self._load()

    def _load(self) -> dict:
        if os.path.exists(self._path):
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                return {"processed_vods": {}, "last_poll_time": None, "stop": False}
        return {"processed_vods": {}, "last_poll_time": None, "stop": False}

    def _save(self) -> None:
        """원자적 저장: 파일 잠금 → tmp 쓰기 → rename"""
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
        lock_path = self._path + ".lock"
        tmp = self._path + ".tmp"
        try:
            lock_fd = os.open(lock_path, os.O_CREAT | os.O_WRONLY)
            import msvcrt
            msvcrt.locking(lock_fd, msvcrt.LK_NBLCK, 1)
        except (OSError, ImportError):
            # 잠금 실패 또는 비-Windows: 잠금 없이 진행
            lock_fd = None

        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._path)
        finally:
            if lock_fd is not None:
                try:
                    import msvcrt
                    msvcrt.locking(lock_fd, msvcrt.LK_UNLCK, 1)
                    os.close(lock_fd)
                except OSError:
                    pass

    def is_processed(self, video_no: str) -> bool:
        with self._lock:
            return video_no in self._data["processed_vods"]

    def get_status(self, video_no: str) -> Optional[str]:
        with self._lock:
            entry = self._data["processed_vods"].get(video_no)
            return entry.get("status") if entry else None

    def update(self, video_no: str, status: str, **kwargs) -> None:
        with self._lock:
            now = datetime.now(KST).isoformat()
            entry = self._data["processed_vods"].get(video_no, {})
            entry["video_no"] = video_no
            entry["status"] = status
            entry["updated_at"] = now
            if status == "processing" and "started_at" not in entry:
                entry["started_at"] = now
            if status == "completed":
                entry["completed_at"] = now
            entry.update(kwargs)
            self._data["processed_vods"][video_no] = entry
            self._save()

    def update_poll_time(self) -> None:
        with self._lock:
            self._data["last_poll_time"] = datetime.now(KST).isoformat()
            self._save()

    def should_stop(self) -> bool:
        with self._lock:
            # 디스크에서 재로드하여 외부 변경 감지
            self._data = self._load()
            return self._data.get("stop", False)

    def request_stop(self) -> None:
        with self._lock:
            self._data["stop"] = True
            self._save()

    def clear_stop(self) -> None:
        with self._lock:
            self._data["stop"] = False
            self._save()

    def get_failed_vods(self, max_retries: int = 3) -> list:
        with self._lock:
            failed = []
            for vno, entry in self._data["processed_vods"].items():
                if entry.get("status") == "error":
                    retry_count = entry.get("retry_count", 0)
                    if retry_count < max_retries:
                        failed.append(vno)
            return failed

    def increment_retry(self, video_no: str) -> None:
        with self._lock:
            entry = self._data["processed_vods"].get(video_no, {})
            entry["retry_count"] = entry.get("retry_count", 0) + 1
            entry["status"] = "pending_retry"
            self._data["processed_vods"][video_no] = entry
            self._save()
