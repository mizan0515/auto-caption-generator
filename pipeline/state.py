"""파이프라인 처리 상태 영속화 (스레드 잠금 + 파일 잠금 포함)"""

import json
import os
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

KST = timezone(timedelta(hours=9))
_TERMINAL_STATUSES = ("completed", "skipped_bootstrap")

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
            prev_status = entry.get("status")
            if prev_status in _TERMINAL_STATUSES and status not in _TERMINAL_STATUSES:
                preserved = dict(entry)
                preserved["updated_at"] = now
                for field in ("progress", "publish_status", "publish_vod_count"):
                    if field in kwargs:
                        preserved[field] = kwargs[field]
                self._data["processed_vods"][key] = preserved
                self._save()
                return
            entry["video_no"] = video_no
            if channel_id:
                entry["channel_id"] = channel_id
            entry["status"] = status
            entry["updated_at"] = now
            if status not in ("error", "pending_retry"):
                entry.pop("error", None)
            if status != "completed":
                entry.pop("completed_at", None)
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
        """재시도 대상 VOD 목록을 (video_no, channel_id) 튜플 리스트로 반환.

        포함 status:
          - "error": process_vod 가 예외로 끝난 일반적인 실패
          - "pending_retry": increment_retry() 직후 데몬 크래시 등으로 남은
            좀비. 이걸 포함하지 않으면 수동 개입 전까지 영영 재시도 안 된다.
        """
        with self._lock:
            self._data = self._load()
            failed: list[tuple[str, Optional[str]]] = []
            for _key, entry in self._data["processed_vods"].items():
                if entry.get("status") in ("error", "pending_retry"):
                    retry_count = entry.get("retry_count", 0)
                    if retry_count < max_retries:
                        vno = entry.get("video_no", _key)
                        cid = entry.get("channel_id")
                        failed.append((vno, cid))
            return failed

    # 진행 중 상태를 terminal 로 되돌리지 않는 논리 판정용 상수.
    # 여기 포함된 status 는 "아직 처리 중" 으로 간주되며, heartbeat 기반의
    # staleness 체크로만 좀비 판정한다.
    _NONTERMINAL_PROCESSING = (
        "collecting", "analyzing", "transcribing", "chunking",
        "summarizing", "saving",
    )

    def get_stale_vods(self, stale_after_sec: int = 3600) -> list[tuple[str, Optional[str]]]:
        """좀비(진행 중 status 로 박제됐는데 updated_at 이 오래된) VOD 반환.

        daemon 이 processing 도중 크래시하면 status 가 "collecting"/"transcribing"/
        ... 등 non-terminal 로 남아 retry 경로에도, new-vod 경로에도 안 잡힌다.
        heartbeat 가 정상 동작 중인 VOD 는 updated_at 이 주기적으로 갱신되므로
        stale_after_sec 내에 업데이트가 있으면 여기서 제외된다.

        Args:
            stale_after_sec: updated_at 과 현재 사이 간격이 이 값 이상이면 좀비
                로 판정. 기본 1시간 — download heartbeat (30s) 와 Whisper stall
                watchdog (600s) 보다 충분히 크다.

        Returns:
            (video_no, channel_id) 튜플 리스트.
        """
        with self._lock:
            self._data = self._load()
            now = datetime.now(KST)
            stale: list[tuple[str, Optional[str]]] = []
            for _key, entry in self._data["processed_vods"].items():
                if entry.get("status") not in self._NONTERMINAL_PROCESSING:
                    continue
                ts = entry.get("updated_at")
                if not ts:
                    # updated_at 이 없는 건 무조건 좀비로 본다 (아주 오래된 기록)
                    stale.append((entry.get("video_no", _key), entry.get("channel_id")))
                    continue
                try:
                    dt = datetime.fromisoformat(ts)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=KST)
                    age = (now - dt).total_seconds()
                except (ValueError, TypeError):
                    age = stale_after_sec + 1  # 파싱 실패는 좀비 처리
                if age >= stale_after_sec:
                    stale.append((entry.get("video_no", _key), entry.get("channel_id")))
            return stale

    def mark_zombie_as_error(self, video_no: str, channel_id: Optional[str] = None,
                              reason: str = "zombie recovery") -> None:
        """좀비 VOD 를 status="error" 로 전환. retry_count 는 보존한다.

        get_stale_vods() 와 쌍으로 사용. 이후 get_failed_vods 가 재시도 큐에
        넣어줄 수 있게 한다.
        """
        with self._lock:
            self._data = self._load()
            key = self._resolve_key(video_no, channel_id)
            entry = self._data["processed_vods"].get(key)
            if not entry:
                return
            if entry.get("status") in self._NONTERMINAL_PROCESSING:
                entry["status"] = "error"
                entry["error"] = reason
                entry["updated_at"] = datetime.now(KST).isoformat()
                self._data["processed_vods"][key] = entry
                self._save()

    def recover_orphaned_processing(
        self,
        reason: str = "orphan recovery (daemon restart)",
    ) -> list[tuple[str, Optional[str]]]:
        """현재 실행 중인 worker 가 없다고 가정할 수 있는 시점에 non-terminal
        엔트리를 즉시 error 로 전환한다.

        사용처:
          - daemon 프로세스/스레드가 새로 시작될 때
          - pause 후 resume 로 새 루프를 띄울 때

        의도:
          기존 stale_after_sec(기본 1시간) 를 기다리지 않고, 직전 데몬이 죽으며
          남긴 `collecting/transcribing/...` 상태를 곧바로 재시도 가능 상태로
          돌린다. process_vod 의 RESUME 캐시(work_dir mp4/wav/srt/chat json) 가
          있으므로 다음 재시도는 가능한 지점부터 재사용된다.
        """
        with self._lock:
            self._data = self._load()
            recovered: list[tuple[str, Optional[str]]] = []
            changed = False
            now = datetime.now(KST).isoformat()
            for _key, entry in self._data["processed_vods"].items():
                if entry.get("status") not in self._NONTERMINAL_PROCESSING:
                    continue
                entry["status"] = "error"
                entry["error"] = reason
                entry["updated_at"] = now
                recovered.append((entry.get("video_no", _key), entry.get("channel_id")))
                changed = True
            if changed:
                self._save()
            return recovered

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
