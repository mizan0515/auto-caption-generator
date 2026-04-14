"""시스템 트레이 기반 파이프라인 런처

Windows 시스템 트레이에 상주하며 파이프라인 데몬을 백그라운드 스레드로 실행.
트레이 아이콘 우클릭 메뉴:
  - 상태 확인: 현재 처리 중인 VOD 정보 표시
  - 로그 열기: 로그 파일을 기본 텍스트 에디터로 열기
  - 출력 폴더 열기: output 디렉터리를 탐색기로 열기
  - 설정 열기: pipeline_config.json을 에디터로 열기
  - 일시정지 / 재개: 폴링 일시정지/재개
  - 종료: 파이프라인 중지 후 트레이 종료
"""

import logging
import os
import subprocess
import sys
import threading
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
_ROOT = str(Path(__file__).resolve().parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

try:
    import pystray
    from PIL import Image
except ImportError:
    print("필요한 패키지가 없습니다. 설치 후 재실행하세요:")
    print("  pip install pystray Pillow")
    sys.exit(1)

from pipeline.config import load_config, ensure_dirs, _config_path
from pipeline.state import PipelineState
from pipeline.utils import setup_logging

logger = logging.getLogger("pipeline")


class PipelineTray:
    def __init__(self):
        self.cfg = load_config()
        ensure_dirs(self.cfg)

        self.state_path = os.path.join(self.cfg["output_dir"], "pipeline_state.json")
        self.state = PipelineState(self.state_path)
        self.state.clear_stop()

        self.log_dir = os.path.join(self.cfg["output_dir"], "logs")
        self.log_path = os.path.join(self.log_dir, "pipeline.log")

        self._daemon_thread = None
        self._running = False
        self._paused = False
        self.icon = None

    def _load_icon(self) -> Image.Image:
        """트레이 아이콘 로드. chzzk.ico 없으면 기본 아이콘 생성."""
        ico_path = Path(_ROOT) / "resources" / "chzzk.ico"
        if ico_path.exists():
            try:
                return Image.open(ico_path)
            except Exception:
                pass
        # 폴백: 16x16 녹색 사각형
        img = Image.new("RGB", (64, 64), color=(0, 180, 100))
        return img

    def _get_status_text(self) -> str:
        """현재 파이프라인 상태 텍스트"""
        if self._paused:
            return "일시정지됨"
        if not self._running:
            return "중지됨"

        # 처리 중인 VOD 확인
        data = self.state._load()
        processing = []
        for vno, entry in data.get("processed_vods", {}).items():
            status = entry.get("status", "")
            if status in ("collecting", "analyzing", "transcribing", "chunking", "summarizing", "saving"):
                processing.append(f"[{vno}] {status}")

        if processing:
            return "처리 중: " + ", ".join(processing)
        return "대기 중 (모니터링)"

    def _on_status(self, icon, item):
        """상태 알림 표시"""
        status = self._get_status_text()
        icon.notify(status, "파이프라인 상태")

    def _on_open_log(self, icon, item):
        """로그 파일 열기"""
        if os.path.exists(self.log_path):
            os.startfile(self.log_path)
        else:
            icon.notify("로그 파일이 아직 없습니다.", "알림")

    def _on_open_output(self, icon, item):
        """출력 폴더 열기"""
        output_dir = os.path.abspath(self.cfg["output_dir"])
        os.makedirs(output_dir, exist_ok=True)
        os.startfile(output_dir)

    def _on_open_config(self, icon, item):
        """설정 파일을 텍스트 에디터로 열기"""
        config_path = str(_config_path())
        os.startfile(config_path)

    def _on_settings_ui(self, icon, item):
        """설정 GUI 열기"""
        from pipeline.settings_ui import open_settings

        def _on_save(new_cfg):
            self.cfg = new_cfg
            logger.info("설정이 변경되었습니다. 다음 폴링부터 적용됩니다.")
            if self.icon:
                self.icon.notify("설정이 저장되었습니다.\n다음 폴링부터 적용됩니다.", "설정 변경")

        open_settings(on_save=_on_save)

    def _on_pause_resume(self, icon, item):
        """일시정지 / 재개"""
        if self._paused:
            self._paused = False
            self.state.clear_stop()
            logger.info("파이프라인 재개됨")
            icon.notify("파이프라인이 재개되었습니다.", "재개")
            # 데몬 스레드 재시작
            self._start_daemon()
        else:
            self._paused = True
            self.state.request_stop()
            logger.info("파이프라인 일시정지됨")
            icon.notify("파이프라인이 일시정지되었습니다.", "일시정지")

    def _get_pause_text(self, item):
        return "재개" if self._paused else "일시정지"

    def _on_quit(self, icon, item):
        """종료"""
        logger.info("트레이 앱 종료 요청")
        self._running = False
        self.state.request_stop()
        icon.stop()

    def _start_daemon(self):
        """데몬 스레드 시작"""
        if self._daemon_thread and self._daemon_thread.is_alive():
            return  # 이미 실행 중
        self._running = True
        self._daemon_thread = threading.Thread(
            target=self._run_daemon_loop, daemon=True, name="pipeline-daemon"
        )
        self._daemon_thread.start()

    def _run_daemon_loop(self):
        """데몬 메인 루프 (스레드에서 실행)"""
        import time
        from pipeline.config import get_cookies, validate_cookies
        from pipeline.monitor import check_new_vods
        from pipeline.main import process_vod
        from pipeline.models import VODInfo

        log_logger = setup_logging(self.log_dir)
        channel_id = self.cfg["target_channel_id"]
        poll_interval = self.cfg.get("poll_interval_sec", 300)
        cookies = get_cookies(self.cfg)

        log_logger.info("=" * 60)
        log_logger.info("  파이프라인 데몬 시작 (트레이 모드)")
        log_logger.info(f"  채널: {channel_id}")
        log_logger.info(f"  스트리머: {self.cfg.get('streamer_name', '?')}")
        log_logger.info(f"  폴링 간격: {poll_interval}초")
        log_logger.info("=" * 60)

        if not validate_cookies(self.cfg):
            log_logger.error("쿠키가 설정되지 않았습니다.")
            if self.icon:
                self.icon.notify(
                    "쿠키가 설정되지 않았습니다.\npipeline_config.json의 cookies를 설정하세요.",
                    "오류",
                )
            return

        while self._running and not self._paused:
            if self.state.should_stop():
                log_logger.info("종료 요청 감지")
                break

            try:
                new_vods = check_new_vods(channel_id, cookies, self.state)

                for vod in new_vods:
                    if not self._running or self._paused:
                        break
                    if self.icon:
                        self.icon.notify(f"새 VOD 처리 시작: {vod.title[:40]}", "새 VOD")
                    process_vod(vod, self.cfg, self.state, log_logger)
                    if self.icon:
                        self.icon.notify(f"VOD 처리 완료: {vod.title[:40]}", "완료")

                # 실패 VOD 재시도
                failed = self.state.get_failed_vods(max_retries=3)
                for video_no in failed:
                    if not self._running or self._paused:
                        break
                    log_logger.info(f"실패 VOD 재시도: {video_no}")
                    self.state.increment_retry(video_no)
                    try:
                        from content.network import NetworkManager
                        _, _, _, _, _, metadata = NetworkManager.get_video_info(video_no, cookies)
                        vod = VODInfo(
                            video_no=video_no,
                            title=metadata.get("title", ""),
                            channel_id=channel_id,
                            channel_name=metadata.get("channelName", ""),
                            duration=metadata.get("duration", 0),
                            publish_date=metadata.get("createdDate", ""),
                            category=metadata.get("category", ""),
                        )
                        process_vod(vod, self.cfg, self.state, log_logger)
                    except Exception as e:
                        log_logger.error(f"재시도 실패: {e}")

            except Exception as e:
                log_logger.error(f"메인 루프 오류: {e}")

            # 폴링 대기 (1초 단위로 끊어서 종료 감지)
            for _ in range(poll_interval):
                if not self._running or self._paused:
                    break
                time.sleep(1)

    def run(self):
        """트레이 앱 시작"""
        menu = pystray.Menu(
            pystray.MenuItem("상태 확인", self._on_status),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("설정", self._on_settings_ui),
            pystray.MenuItem("로그 열기", self._on_open_log),
            pystray.MenuItem("출력 폴더 열기", self._on_open_output),
            pystray.MenuItem("설정 파일 직접 편집", self._on_open_config),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(self._get_pause_text, self._on_pause_resume),
            pystray.MenuItem("종료", self._on_quit),
        )

        self.icon = pystray.Icon(
            name="chzzk-pipeline",
            icon=self._load_icon(),
            title="Chzzk VOD 파이프라인",
            menu=menu,
        )

        # 트레이 표시 직후 데몬 시작
        self.icon.run(setup=lambda icon: self._start_daemon())


def main():
    app = PipelineTray()
    app.run()


if __name__ == "__main__":
    main()
