"""파이프라인 처리 상태 영속화 (스레드 잠금 + 파일 잠금 포함)"""

import json
import os
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

KST = timezone(timedelta(hours=9))

# 파일 잠금 재시도 파라미터.
# daemon 스레드 ↔ `--process` 서브프로세스 간 inter-process race 를 커버한다.
# 일반 _save() 는 수 밀리초 이내에 끝나므로 대부분 1~2회 안에 성공한다.
_LOCK_RETRY_COUNT = 40          # 40회 * 25ms = 최대 1초 대기
_LOCK_RETRY_INTERVAL_SEC = 0.025


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

    _EMPTY = {"processed_vods": {}, "last_poll_time": None, "stop": False}

    def _load(self) -> dict:
        """디스크에서 상태를 로드. 다른 프로세스의 원자적 rename 사이에 잠깐
        JSON 이 불완전하게 보이거나 (JSONDecodeError), Windows 에서 reader/writer
        겹침으로 PermissionError 가 날 수 있어 짧게 재시도한다.

        CRITICAL — OSError 를 삼켜 빈 dict 를 반환하면 안 된다. 호출자는 거의
        항상 `self._data = self._load()` 직후 `_save()` 를 호출하므로, 빈 dict
        반환은 곧 **디스크 상태를 zero-out 하는 data loss** 를 의미한다.
        따라서 전 retry 가 실패하면 예외를 올려 호출 mutation 을 중단시킨다.
        """
        if not os.path.exists(self._path):
            return dict(self._EMPTY)
        last_err: Optional[Exception] = None
        for _ in range(5):
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # 스키마 보강: 레거시/부분 쓰기 파일에 missing key 가 있어도
                # 호출자가 `data["processed_vods"]` 로 KeyError 를 맞지 않도록.
                for k, v in self._EMPTY.items():
                    data.setdefault(k, v if not isinstance(v, dict) else dict(v))
                return data
            except (json.JSONDecodeError, OSError) as e:
                last_err = e
                time.sleep(0.02)
                continue
        # 재시도 소진 — 호출 mutation 이 진행되면 state 를 덮어쓸 수 있으니
        # 예외를 올려 중단시킨다. `_save()` 경로로 빈 dict 가 흘러가지 않게.
        raise RuntimeError(
            f"PipelineState: failed to load {self._path} after retries: {last_err}"
        ) from last_err

    def _save(self) -> None:
        """원자적 저장: 파일 잠금 (재시도 포함) → 고유 tmp 쓰기 → rename

        tmp 파일명은 pid + threadid 조합으로 고유해야 한다. 이전엔 고정된
        `{path}.tmp` 를 써서 두 프로세스가 동시에 tmp 를 쓰면 서로를 클로버하고
        `os.replace` 가 PermissionError 로 터졌다.
        """
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
        lock_path = self._path + ".lock"
        tmp = f"{self._path}.{os.getpid()}.{threading.get_ident()}.tmp"
        lock_fd = self._acquire_file_lock(lock_path)

        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            # Windows 에서 리더가 파일을 연 순간 os.replace 가 일시적으로 실패할
            # 수 있다 (PermissionError / SHARING_VIOLATION). 짧게 재시도.
            for attempt in range(5):
                try:
                    os.replace(tmp, self._path)
                    break
                except PermissionError:
                    if attempt == 4:
                        raise
                    time.sleep(0.02)
        finally:
            # tmp 가 아직 남아있으면 정리 (os.replace 실패 케이스)
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            self._release_file_lock(lock_fd)

    @staticmethod
    def _acquire_file_lock(lock_path: str):
        """LK_NBLCK 를 재시도하여 inter-process 잠금을 실제로 획득한다.

        이전 구현: 한 번만 시도하고 실패하면 `lock_fd=None` 으로 폴백 — 즉
        잠금 없이 저장해 subprocess 와 race. 이제는 1초까지 재시도하고, 그래도
        실패하면 어쩔 수 없이 잠금 없이 진행 (기능 유지가 data-consistency 보다
        중요한 로깅 경로를 위해).
        """
        try:
            import msvcrt
        except ImportError:
            return None  # 비-Windows
        try:
            lock_fd = os.open(lock_path, os.O_CREAT | os.O_WRONLY)
        except OSError:
            return None
        for _ in range(_LOCK_RETRY_COUNT):
            try:
                msvcrt.locking(lock_fd, msvcrt.LK_NBLCK, 1)
                return lock_fd
            except OSError:
                time.sleep(_LOCK_RETRY_INTERVAL_SEC)
        # 재시도 소진 — close & None 반환. 저장은 계속 진행.
        try:
            os.close(lock_fd)
        except OSError:
            pass
        return None

    @staticmethod
    def _release_file_lock(lock_fd) -> None:
        if lock_fd is None:
            return
        try:
            import msvcrt
            msvcrt.locking(lock_fd, msvcrt.LK_UNLCK, 1)
        except (OSError, ImportError):
            pass
        try:
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
            # 서브프로세스(`--process`) 가 새로 써넣은 엔트리를 간과하지 않도록
            # 읽기 경로에서도 디스크를 재로드한다. 쓰기 경로에서는 반드시 필요.
            self._data = self._load()
            key = self._resolve_key(video_no, channel_id)
            return key in self._data["processed_vods"]

    def get_status(self, video_no: str, channel_id: Optional[str] = None) -> Optional[str]:
        with self._lock:
            self._data = self._load()
            key = self._resolve_key(video_no, channel_id)
            entry = self._data["processed_vods"].get(key)
            return entry.get("status") if entry else None

    def update(self, video_no: str, status: str, channel_id: Optional[str] = None, **kwargs) -> None:
        with self._lock:
            # 중요: 디스크 재로드. 이전에는 `self._data` 의 stale 캐시로
            # 서브프로세스 쓰기를 무심코 덮어썼다 (예: 대시보드가 spawn 한
            # `python -m pipeline.main --process` 가 먼저 마친 상태를 daemon 이
            # clobber). 자세한 분석은 PR #59 참조.
            self._data = self._load()
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
            self._data = self._load()
            self._data["last_poll_time"] = datetime.now(KST).isoformat()
            self._save()

    def should_stop(self) -> bool:
        with self._lock:
            # 디스크에서 재로드하여 외부 변경 감지
            self._data = self._load()
            return self._data.get("stop", False)

    def request_stop(self) -> None:
        with self._lock:
            # 재로드 누락 시 subprocess 가 방금 기록한 processed_vods 엔트리를
            # stale 캐시로 덮어써 지워버린다. PR #59 가 update() 는 고쳤지만
            # 이 경로가 누락돼 있었다.
            self._data = self._load()
            self._data["stop"] = True
            self._save()

    def clear_stop(self) -> None:
        with self._lock:
            self._data = self._load()
            self._data["stop"] = False
            self._save()

    def get_failed_vods(self, max_retries: int = 3) -> list[tuple[str, Optional[str]]]:
        """실패한 VOD 목록을 (video_no, channel_id) 튜플 리스트로 반환."""
        with self._lock:
            self._data = self._load()
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
            self._data = self._load()
            key = self._resolve_key(video_no, channel_id)
            entry = self._data["processed_vods"].get(key, {})
            entry["retry_count"] = entry.get("retry_count", 0) + 1
            entry["status"] = "pending_retry"
            self._data["processed_vods"][key] = entry
            self._save()

    def remove_entry(self, key: str) -> bool:
        """processed_vods 에서 단일 엔트리 삭제.

        dashboard 의 직접 파일 편집 경로가 _lock 을 우회해 daemon 과 race 를
        일으켰다. 모든 상태 mutation 은 반드시 이 메서드를 거친다.
        """
        with self._lock:
            # 외부(서브프로세스 `--process` 등) 변경 반영을 위해 재로드
            self._data = self._load()
            if key in self._data.get("processed_vods", {}):
                del self._data["processed_vods"][key]
                self._save()
                return True
            return False

    def clear_errors(self, include_pending_retry: bool = True) -> int:
        """status == 'error' (옵션: 'pending_retry') 엔트리를 일괄 제거.

        Returns:
            제거된 엔트리 수.

        Note:
            daemon 의 재시도 루프(`get_failed_vods` → `increment_retry`) 와
            동시에 호출될 수 있지만 _lock 직렬화 덕에 안전하다. 사용자가 명시
            적으로 "오류 기록 일괄 제거" 를 눌렀을 때의 의도된 동작: 제거된
            엔트리는 이후 재시도 대상에서도 함께 빠진다.
        """
        statuses = {"error"}
        if include_pending_retry:
            statuses.add("pending_retry")
        with self._lock:
            self._data = self._load()
            targets = [
                k for k, v in self._data.get("processed_vods", {}).items()
                if v.get("status") in statuses
            ]
            for k in targets:
                del self._data["processed_vods"][k]
            if targets:
                self._save()
            return len(targets)
