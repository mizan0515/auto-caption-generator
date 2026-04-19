"""파이프라인 백그라운드 데몬.

이전에는 `tray_app.py` 의 `PipelineTray` 안에 데몬 루프가 내장돼 있었고,
대시보드는 별도 프로세스로 떠서 파일 기반 IPC (`pipeline/control.py`) 로
제어했다. Windows 11 이 새 앱의 트레이 아이콘을 기본적으로 숨기는 바람에
트레이가 "있으나 안 보이는" UX 문제가 반복돼 트레이를 아예 제거하고
대시보드 프로세스가 데몬을 직접 소유하도록 재구성함.

대시보드 창이 닫히면 `stop()` 으로 종료한다. 파일 IPC 는 필요 없다 —
대시보드가 데몬 인스턴스 메서드를 직접 호출한다.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger("pipeline")


class PipelineDaemon:
    """파이프라인 폴링 루프를 별도 스레드로 실행.

    `Dashboard` 가 생성 시점에 인스턴스화하고 `start()` 를 호출한다. GUI 종료 시
    `stop()` 으로 정리.
    """

    def __init__(self, cfg: dict, state, log_dir: str,
                 notify: Optional[Callable[[str, str], None]] = None):
        """
        Args:
            cfg: pipeline_config.json 로드 결과
            state: PipelineState 인스턴스 (이미 생성된 것을 주입받음)
            log_dir: setup_logging 에 넘길 로그 디렉터리
            notify: (title, message) 받는 GUI 알림 콜백. 없으면 무시.
        """
        self.cfg = cfg
        self.state = state
        self.log_dir = log_dir
        self._notify = notify or (lambda title, msg: None)

        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._paused = False
        self._log_logger: Optional[logging.Logger] = None
        self._lock_fd = None
        self._lock_path = os.path.join(self.cfg["output_dir"], "pipeline_daemon.lock")

    # ---------- public API ----------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        if not self._acquire_single_instance_lock():
            logger.warning("이미 다른 파이프라인 데몬이 실행 중이어서 시작을 건너뜁니다.")
            self._notify("중복 실행 방지", "이미 다른 파이프라인 데몬이 실행 중입니다.")
            return
        self._running = True
        self._paused = False
        self.state.clear_stop()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="pipeline-daemon"
        )
        self._thread.start()

    def pause(self) -> None:
        if self._paused:
            return
        self._paused = True
        self.state.request_stop()
        logger.info("파이프라인 일시정지됨")
        self._notify("일시정지", "파이프라인이 일시정지되었습니다.")

    def resume(self) -> None:
        if not self._paused:
            return
        self._paused = False
        self.state.clear_stop()
        logger.info("파이프라인 재개됨")
        self._notify("재개", "파이프라인이 재개되었습니다.")
        # 스레드가 루프 조건으로 빠져나간 상태면 새로 띄움
        if not (self._thread and self._thread.is_alive()):
            self.start()

    def stop(self, timeout: float = 5.0) -> None:
        """GUI 종료 시 호출. 루프 종료 요청 + join (timeout)."""
        self._running = False
        self.state.request_stop()
        th = self._thread
        if th and th.is_alive():
            th.join(timeout=timeout)
        self._release_single_instance_lock()

    def is_paused(self) -> bool:
        return self._paused

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def get_status_text(self) -> str:
        if self._paused:
            return "일시정지됨"
        if not self.is_running():
            return "중지됨"
        data = self.state._load()
        processing = []
        for vno, entry in data.get("processed_vods", {}).items():
            status = entry.get("status", "")
            if status in (
                "collecting", "analyzing", "transcribing",
                "chunking", "summarizing", "saving",
            ):
                processing.append(f"[{vno}] {status}")
        if processing:
            return "처리 중: " + ", ".join(processing)
        return "대기 중 (모니터링)"

    def update_config(self, new_cfg: dict) -> None:
        """설정 GUI 에서 저장 후 호출. 다음 폴링부터 적용.

        실제 hot-reload 는 `_run_loop` 가 매 iteration 마다 `self.cfg` 에서
        channel_id / poll_interval / cookies 를 재구성하는 방식으로 동작한다.
        여기선 단순 swap 만 한다 (dict 참조 재대입은 GIL 덕에 atomic).
        """
        self.cfg = new_cfg
        self._lock_path = os.path.join(self.cfg["output_dir"], "pipeline_daemon.lock")
        logger.info("데몬 설정 갱신 — 다음 폴링부터 적용")

    def _acquire_single_instance_lock(self) -> bool:
        if self._lock_fd is not None:
            return True
        try:
            import msvcrt
        except ImportError:
            return True

        os.makedirs(os.path.dirname(self._lock_path) or ".", exist_ok=True)
        try:
            lock_fd = os.open(self._lock_path, os.O_CREAT | os.O_WRONLY)
        except OSError:
            return False
        try:
            msvcrt.locking(lock_fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            os.close(lock_fd)
            return False
        self._lock_fd = lock_fd
        return True

    def _release_single_instance_lock(self) -> None:
        if self._lock_fd is None:
            return
        try:
            import msvcrt
            msvcrt.locking(self._lock_fd, msvcrt.LK_UNLCK, 1)
        except (ImportError, OSError):
            pass
        try:
            os.close(self._lock_fd)
        except OSError:
            pass
        self._lock_fd = None

    # ---------- internal ----------

    def _run_loop(self) -> None:
        from pipeline.config import get_cookies, validate_cookies
        from pipeline.monitor import check_new_vods
        from pipeline.main import process_vod
        from pipeline.models import VODInfo
        from pipeline.utils import setup_logging

        log_logger = setup_logging(self.log_dir)
        self._log_logger = log_logger

        log_logger.info("=" * 60)
        log_logger.info("  파이프라인 데몬 시작 (대시보드 내장 모드)")
        log_logger.info(f"  채널: {self.cfg.get('target_channel_id', '?')}")
        log_logger.info(f"  스트리머: {self.cfg.get('streamer_name', '?')}")
        log_logger.info(f"  폴링 간격: {self.cfg.get('poll_interval_sec', 300)}초")
        log_logger.info("=" * 60)

        if not validate_cookies(self.cfg):
            log_logger.error("쿠키가 설정되지 않았습니다.")
            self._notify(
                "오류",
                "쿠키가 설정되지 않았습니다.\npipeline_config.json의 cookies를 설정하세요.",
            )
            self._release_single_instance_lock()
            return

        while self._running and not self._paused:
            if self.state.should_stop():
                log_logger.info("종료 요청 감지")
                break
            # 매 iteration 마다 cfg 재평가 — 설정 UI 의 저장 후 update_config()
            # 로 교체된 self.cfg 가 즉시 반영된다. 이전엔 루프 밖에서 한 번만
            # 캡처해서 쿠키 갱신/채널 변경/폴링 간격 변경이 전부 무시됐다.
            channel_id = self.cfg["target_channel_id"]
            poll_interval = self.cfg.get("poll_interval_sec", 300)
            cookies = get_cookies(self.cfg)
            try:
                new_vods = check_new_vods(channel_id, cookies, self.state)
                for vod in new_vods:
                    if not self._running or self._paused:
                        break
                    self._notify("새 VOD", f"새 VOD 처리 시작: {vod.title[:40]}")
                    process_vod(vod, self.cfg, self.state, log_logger)
                    self._notify("완료", f"VOD 처리 완료: {vod.title[:40]}")

                # 좀비 복구: non-terminal status 로 박제된 VOD 가 있고 heartbeat
                # 가 stale_after_sec 이상 끊겨 있으면 "error" 로 전환해 재시도 큐에
                # 합류시킨다. stale_after_sec 기본 1시간 — heartbeat 30s 와 Whisper
                # stall watchdog (600s) 보다 충분히 큰 margin.
                stale_after = int(self.cfg.get("zombie_stale_after_sec", 3600))
                zombies = self.state.get_stale_vods(stale_after_sec=stale_after)
                for zvno, zcid in zombies:
                    log_logger.warning(
                        f"좀비 VOD 감지 — error 로 전환 후 재시도 큐 합류: "
                        f"[{zvno}] channel={zcid} (updated_at {stale_after}s 경과)"
                    )
                    self.state.mark_zombie_as_error(
                        zvno, zcid,
                        reason=f"zombie recovery (no heartbeat for >{stale_after}s)",
                    )

                # 실패 VOD 재시도
                # NOTE: get_failed_vods 는 (video_no, channel_id) 튜플 리스트를 반환한다.
                # 이전에는 `for video_no in failed:` 로 튜플 전체를 video_no 로 오인해
                # increment_retry 가 튜플 키의 유령 엔트리를 만들었고 (retry_count=0 유지),
                # get_video_info(tuple, ...) 가 [Errno 22] 로 터졌다. 반드시 언패킹.
                failed = self.state.get_failed_vods(max_retries=3)
                for vno, cid in failed:
                    if not self._running or self._paused:
                        break
                    log_logger.info(f"실패 VOD 재시도: [{vno}] channel={cid}")
                    self.state.increment_retry(vno, cid)
                    try:
                        from content.network import NetworkManager
                        _, _, _, _, _, metadata = NetworkManager.get_video_info(
                            vno, cookies
                        )
                        vod = VODInfo(
                            video_no=vno,
                            title=metadata.get("title", ""),
                            channel_id=cid or channel_id,
                            channel_name=metadata.get("channelName", ""),
                            duration=metadata.get("duration", 0),
                            publish_date=metadata.get("createdDate", ""),
                            category=metadata.get("category", ""),
                        )
                        process_vod(vod, self.cfg, self.state, log_logger)
                    except Exception as e:  # noqa: BLE001
                        log_logger.error(f"재시도 실패 [{vno}]: {e}")

            except Exception as e:  # noqa: BLE001
                log_logger.error(f"메인 루프 오류: {e}")

            # 폴링 대기 (1초 단위로 끊어서 종료 감지)
            for _ in range(int(poll_interval)):
                if not self._running or self._paused:
                    break
                time.sleep(1)

        log_logger.info("파이프라인 데몬 루프 종료")
