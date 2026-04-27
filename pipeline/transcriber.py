"""헤드리스 Whisper 자막 생성 래퍼

B05: 타임아웃/스톨 감지 + graceful 실패.

Whisper(transcribe.py)는 in-process 호출이라 thread cancel 이 불가능하다.
대신 worker thread + 진행 callback 타임스탬프 watchdog 으로 행(hang) 을 감지하고
TimeoutError 를 raise 한다. 행이 걸린 thread 는 daemon=True 로 두어 프로세스
종료 시 정리되지만, 동일 프로세스 내에서는 leak 이 남는다 → 호출자(main.py)는
TimeoutError 를 잡아 해당 VOD 만 실패 처리하고 다음 VOD 로 넘어가야 한다.
연속 hang 이 누적되면 daemon 재시작이 권장된다 (state 가 디스크에 저장되므로
재시작 비용은 낮다).
"""

import logging
import sys
import threading
import time
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

logger = logging.getLogger("pipeline")

# 기본 watchdog 값 (config 미지정 시)
DEFAULT_STALL_SEC = 600     # 10분간 진행 callback 없으면 hang 으로 판정
DEFAULT_TIMEOUT_SEC = 0     # 0 = 전체 시간 제한 없음 (10시간 VOD 도 통과)
WATCHDOG_POLL_SEC = 10


def transcribe_video(
    video_path: str,
    progress_func=None,
    stall_sec: int = DEFAULT_STALL_SEC,
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
    initial_prompt_text: str | None = None,
    vad_prescan_workers: int | None = None,
    cancel_check=None,
) -> str:
    """비디오 → SRT.

    Args:
        video_path: 입력 비디오 경로
        progress_func: 외부 progress callback (current, total)
        stall_sec: 진행 콜백이 N초간 없으면 TimeoutError. 0 = 비활성.
        timeout_sec: 전체 실행 시간 상한. 0 = 비활성.
        cancel_check: 호출 시 True 반환하면 cooperative cancel.
            transcribe.py 내부 stop_event 를 set 하여 다음 batch 경계에서 종료
            시키고, 전체 실행은 RuntimeError("cancelled") 로 raise.
            호출자(process_vod) 는 이를 SkipRequested 흐름과 결합.

    Returns:
        SRT 파일 경로

    Raises:
        TimeoutError: stall 또는 전체 timeout 도달
        RuntimeError("cancelled"): cancel_check 가 True 반환
        Exception: Whisper 내부 에러를 그대로 전달
    """
    from transcribe import run_caption_generation

    logger.info(f"자막 생성 시작: {video_path}")

    # worker → main 통신용 mutable 컨테이너
    state = {"srt": None, "error": None}
    last_progress_ts = [time.time()]
    progress_seen = [False]
    last_progress = [(0, 0)]
    last_external_ping_ts = [time.time()]
    stop_event = threading.Event()

    def log_func(msg):
        logger.info(f"  [Whisper] {msg}")

    def prog_func(current, total):
        last_progress_ts[0] = time.time()
        progress_seen[0] = True
        last_progress[0] = (current, total)
        last_external_ping_ts[0] = time.time()
        if progress_func:
            try:
                progress_func(current, total)
            except Exception as cb_err:
                logger.warning(f"progress_func 콜백 에러 무시: {cb_err}")
        if current % 10 == 0 or current == total:
            logger.info(f"  [Whisper] 진행: {current}/{total} 청크")

    files_info = [{
        "path": video_path,
        "time_offset": 0.0,
        "part_num": 1,
        "total_parts": 1,
    }]

    def worker():
        try:
            state["srt"] = run_caption_generation(
                files_info=files_info,
                is_split=False,
                log_func=log_func,
                progress_func=prog_func,
                initial_prompt_text=initial_prompt_text,
                vad_prescan_workers=vad_prescan_workers,
                stop_event=stop_event,
            )
        except Exception as e:
            import traceback
            state["error"] = e
            state["traceback"] = traceback.format_exc()

    t = threading.Thread(target=worker, name="whisper-worker", daemon=True)
    start = time.time()
    t.start()

    while True:
        t.join(timeout=WATCHDOG_POLL_SEC)
        if not t.is_alive():
            break

        elapsed = time.time() - start
        idle = time.time() - last_progress_ts[0]

        # 전체 시간 초과
        if timeout_sec and elapsed > timeout_sec:
            msg = f"Whisper 전체 시간 초과: {elapsed:.0f}s > {timeout_sec}s"
            logger.error(msg)
            raise TimeoutError(msg)

        # 진행 정체 (stall) 감지: 모델 로드/사전스캔 중에는 progress_seen=False 라
        # idle 이 누적될 수 있으므로 첫 진행 콜백이 한번이라도 도달한 후에만 검사한다.
        if stall_sec and progress_seen[0] and idle > stall_sec:
            msg = f"Whisper 진행 정체: {idle:.0f}s 동안 청크 진행 없음 (>{stall_sec}s)"
            logger.error(msg)
            raise TimeoutError(msg)

        # 협력적 cancel — 사용자 스킵 요청 시 다음 batch 경계에서 worker 가
        # stop_event 보고 종료. 실제 worker join 은 batch 길이만큼 더 기다리지만
        # 여기서 stop 신호만 흘리고 watchdog 루프 계속 → worker 가 exit 하면
        # break (line 112) 로 빠져나옴. 그 직후 RuntimeError raise.
        if cancel_check is not None:
            try:
                if cancel_check():
                    if not stop_event.is_set():
                        stop_event.set()
                        logger.info("Whisper cancel 요청 — 다음 batch 경계에서 종료")
            except Exception as cb_err:  # noqa: BLE001
                logger.warning(f"cancel_check 콜백 에러 무시: {cb_err}")

        # 모델 로드 / VAD prescan 처럼 progress callback 이 늦게 오는 구간도
        # 외부 state.updated_at 이 얼지 않도록 heartbeat 를 흘린다.
        if progress_func and (time.time() - last_external_ping_ts[0] >= 30):
            try:
                current, total = last_progress[0]
                progress_func(current, total)
                last_external_ping_ts[0] = time.time()
            except Exception as cb_err:
                logger.warning(f"progress heartbeat 콜백 에러 무시: {cb_err}")

    if state["error"] is not None:
        logger.error(f"Whisper 실행 에러: {state['error']}")
        tb = state.get("traceback")
        if tb:
            logger.error(f"Whisper 실행 트레이스백:\n{tb}")
        raise state["error"]

    # cancel 신호로 종료된 경우 — Whisper 가 부분 SRT 를 반환했어도
    # 처리 중단을 의미. 호출자가 SkipRequested 흐름으로 가도록 raise.
    if stop_event.is_set():
        raise RuntimeError("cancelled")

    srt_path = state["srt"]
    if not srt_path:
        raise RuntimeError("Whisper 가 SRT 경로를 반환하지 않음 (알 수 없는 실패)")

    logger.info(f"자막 생성 완료: {srt_path}")
    return srt_path
