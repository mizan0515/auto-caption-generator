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

    상태 키 전략 (멀티 스트리머 지원):
    - 새 VOD: composite key "{channel_id}:{video_no}" 사용
    - 레거시 (channel_id 없음): 단순 "video_no" 키 유지
    - 조회 시 composite key 우선, 없으면 plain video_no 로 fallback
    """

    def __init__(self, state_path: str):
        self._path = state_path
        self._lock = threading.Lock()
        self._data = self._load()

    @staticmethod
    def make_key(video_no: str, channel_id: Optional[str] = None) -> str:
        """composite key 생성. channel_id 가 있으면 "{channel_id}:{video_no}"."""
        if channel_id:
            return f"{channel_id}:{video_no}"
        return video_no

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

    def _resolve_key(self, video_no: str, channel_id: Optional[str] = None) -> str:
        """composite key 를 우선 탐색, 없으면 plain video_no 로 fallback."""
        if channel_id:
            composite = self.make_key(video_no, channel_id)
            if composite in self._data["processed_vods"]:
                return composite
        # plain key fallback (레거시)
        if video_no in self._data["processed_vods"]:
            return video_no
        # 새 항목이면 composite 사용
        if channel_id:
            return self.make_key(video_no, channel_id)
        return video_no

    def is_processed(self, video_no: str, channel_id: Optional[str] = None) -> bool:
        with self._lock:
            key = self._resolve_key(video_no, channel_id)
            return key in self._data["processed_vods"]

    def get_status(self, video_no: str, channel_id: Optional[str] = None) -> Optional[str]:
        with self._lock:
            key = self._resolve_key(video_no, channel_id)
            entry = self._data["processed_vods"].get(key)
            return entry.get("status") if entry else None

    def update(self, video_no: str, status: str, channel_id: Optional[str] = None, **kwargs) -> None:
        with self._lock:
            now = datetime.now(KST).isoformat()
            key = self._resolve_key(video_no, channel_id)
            entry = self._data["processed_vods"].get(key, {})
            entry["video_no"] = video_no
            if channel_id:
                entry["channel_id"] = channel_id
            entry["status"] = status
            entry["updated_at"] = now
            if status == "processing" and "started_at" not in entry:
                entry["started_at"] = now
            if status == "completed":
                entry["completed_at"] = now
            entry.update(kwargs)
            self._data["processed_vods"][key] = entry
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

    def get_failed_vods(self, max_retries: int = 3) -> list[tuple[str, Optional[str]]]:
        """실패한 VOD 목록을 (video_no, channel_id) 튜플 리스트로 반환."""
        with self._lock:
            failed: list[tuple[str, Optional[str]]] = []
            for _key, entry in self._data["processed_vods"].items():
                if entry.get("status") == "error":
                    retry_count = entry.get("retry_count", 0)
                    if retry_count < max_retries:
                        vno = entry.get("video_no", _key)
                        cid = entry.get("channel_id")
                        failed.append((vno, cid))
            return failed

    def increment_retry(self, video_no: str, channel_id: Optional[str] = None) -> None:
        with self._lock:
            key = self._resolve_key(video_no, channel_id)
            entry = self._data["processed_vods"].get(key, {})
            entry["retry_count"] = entry.get("retry_count", 0) + 1
            entry["status"] = "pending_retry"
            self._data["processed_vods"][key] = entry
            self._save()
