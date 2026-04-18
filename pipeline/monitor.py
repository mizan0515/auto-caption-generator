"""Chzzk VOD 목록 폴링 — 새 다시보기 감지"""

import logging
import re
import sys
import requests
from typing import Optional

from .models import VODInfo
from .state import PipelineState
from .utils import retry

logger = logging.getLogger("pipeline")

CHZZK_API = "https://api.chzzk.naver.com"
HEADERS = {"User-Agent": "Mozilla/5.0"}


def extract_channel_id(url: str) -> Optional[str]:
    m = re.search(r"/([a-f0-9]{32})/", url)
    return m.group(1) if m else None


@retry(max_retries=3, backoff_base=2.0, exceptions=(requests.RequestException,))
def fetch_vod_list(channel_id: str, cookies: dict, page: int = 0, size: int = 20) -> list[dict]:
    """채널의 다시보기 목록 API 호출"""
    url = (
        f"{CHZZK_API}/service/v1/channels/{channel_id}/videos"
        f"?sortType=LATEST&pagingType=PAGE&page={page}&size={size}"
    )
    resp = requests.get(url, cookies=cookies, headers=HEADERS, timeout=15)
    resp.raise_for_status()

    data = resp.json()
    content = data.get("content", {})
    video_list = content.get("data", [])
    return video_list


def parse_vod_info(raw: dict, channel_id: str) -> VODInfo:
    from .config import derive_streamer_id
    channel_name = raw.get("channel", {}).get("channelName", "")
    return VODInfo(
        video_no=str(raw.get("videoNo", "")),
        title=raw.get("videoTitle", "제목 없음"),
        channel_id=channel_id,
        channel_name=channel_name,
        duration=raw.get("duration", 0),
        publish_date=raw.get("liveOpenDate", raw.get("publishDate", "")),
        thumbnail_url=raw.get("thumbnailImageUrl", ""),
        category=raw.get("videoCategoryValue", ""),
        streamer_id=derive_streamer_id(channel_id, channel_name),
    )


def _ask_bootstrap_mode(existing_count: int) -> tuple[str, int]:
    """대화형으로 bootstrap 정책을 묻는다.

    반환: (mode, n)
      mode = "skip_all" | "latest_n"
      n    = latest_n 모드일 때 처리할 개수 (skip_all 이면 0)

    TTY가 없거나 입력이 막히면 안전한 기본값("skip_all", 0) 반환.
    """
    if not sys.stdin or not sys.stdin.isatty():
        logger.warning("비대화형 환경 — bootstrap 기본값 'skip_all' 로 진행")
        return ("skip_all", 0)

    print()
    print("=" * 60)
    print(f"  [Bootstrap] 최초 실행 — 채널에 기존 VOD {existing_count}개가 있습니다.")
    print("=" * 60)
    print()
    print("  처리 방식을 선택하세요:")
    print("    [1] 기존 VOD 모두 스킵 (이후 새로 올라오는 것만 처리)  ← 권장")
    print("    [2] 최신 N개만 처리")
    print()

    while True:
        try:
            choice = input("  선택 (1/2) [기본 1]: ").strip() or "1"
        except (EOFError, KeyboardInterrupt):
            print()
            return ("skip_all", 0)

        if choice == "1":
            return ("skip_all", 0)
        if choice == "2":
            try:
                n_str = input(f"  몇 개 처리? (1~{existing_count}) [기본 1]: ").strip() or "1"
                n = int(n_str)
                n = max(1, min(n, existing_count))
                return ("latest_n", n)
            except ValueError:
                print("  숫자를 입력하세요.")
                continue
            except (EOFError, KeyboardInterrupt):
                print()
                return ("skip_all", 0)
        print("  1 또는 2를 입력하세요.")


def check_new_vods(
    channel_id: str,
    cookies: dict,
    state: PipelineState,
    cfg: Optional[dict] = None,
    page: int = 0,
    size: int = 20,
) -> list[VODInfo]:
    """새로운 VOD 감지. 이미 처리된/처리중인 VOD는 제외.

    ★ 최초 실행 (state가 비어있음) 시:
       cfg['bootstrap_mode'] 에 따라 동작:
         - None       : 대화형 질문 (TTY 없으면 skip_all)
         - "skip_all" : 기존 VOD 모두 스킵
         - "latest_n" : 최신 N개만 처리 (N = cfg['bootstrap_latest_n'])
       선택 결과는 cfg에 저장되어 다음 실행부터는 묻지 않음.
    """
    logger.info(f"VOD 목록 폴링: 채널 {channel_id[:8]}...")
    try:
        raw_list = fetch_vod_list(channel_id, cookies, page, size)
    except requests.RequestException as e:
        logger.error(f"VOD 목록 조회 실패: {e}")
        return []

    # 최초 실행 여부: processed_vods 가 비어있고 last_poll_time 도 없으면 bootstrap
    # 최초 실행 여부: 해당 채널에 대한 처리 기록이 없고 poll_time 도 없으면 bootstrap
    # 멀티 스트리머 시 채널별 bootstrap 판단이 이상적이지만,
    # Slice 1 에서는 전역 bootstrap (기존 동작) 을 유지한다.
    is_bootstrap = (
        not state._data.get("processed_vods")
        and state._data.get("last_poll_time") is None
    )

    if is_bootstrap:
        mode = (cfg or {}).get("bootstrap_mode")
        n = (cfg or {}).get("bootstrap_latest_n", 1)

        if mode is None or mode == "":
            # 매번 대화형 질문 (config에 자동 저장하지 않음 — 명시적 설정 시에만 사용)
            mode, n = _ask_bootstrap_mode(len(raw_list))
            logger.info(f"  이번 실행 선택: mode={mode}, n={n}")
            logger.info(
                "  (매번 묻지 않으려면 설정 GUI 또는 pipeline_config.json 의 "
                "bootstrap_mode 필드를 'skip_all' 또는 'latest_n' 으로 설정하세요)"
            )

        logger.info("=" * 60)
        if mode == "latest_n" and n > 0:
            logger.info(f"  [Bootstrap] 최신 {n}개 VOD만 처리, 나머지는 스킵합니다.")
        else:
            logger.info(f"  [Bootstrap] 기존 VOD {len(raw_list)}개를 모두 스킵합니다.")
        logger.info("  (이후 폴링부터 새로 올라오는 VOD만 처리됩니다)")
        logger.info("=" * 60)

        # raw_list 는 LATEST 정렬 (최신이 앞) — 앞에서 n개만 처리 대상
        process_count = n if mode == "latest_n" else 0
        new_vods = []
        for idx, raw in enumerate(raw_list):
            video_no = str(raw.get("videoNo", ""))
            if not video_no:
                continue
            if idx < process_count:
                vod = parse_vod_info(raw, channel_id)
                new_vods.append(vod)
                logger.info(f"  처리 대상 [{vod.video_no}] {vod.title} ({vod.duration}s)")
            else:
                state.update(
                    video_no,
                    status="skipped_bootstrap",
                    channel_id=channel_id,
                    title=raw.get("videoTitle", ""),
                )
        state.update_poll_time()
        return new_vods

    new_vods = []
    for raw in raw_list:
        video_no = str(raw.get("videoNo", ""))
        if not video_no:
            continue

        existing_status = state.get_status(video_no, channel_id=channel_id)
        # 처리됨/처리중/스킵됨/실패(재시도 대기 중) 모두 제외.
        # "error" / "pending_retry" 를 포함하는 이유:
        #   check_new_vods 와 get_failed_vods 가 둘 다 재시도를 시도하면 같은
        #   VOD 가 폴링당 2회 실행되고, retry_count 는 get_failed_vods 경로
        #   에서만 증가한다. 결과적으로 max_retries=3 제한이 사실상 6회에
        #   가깝게 동작하고 Claude/Whisper 호출이 낭비된다. 재시도는
        #   get_failed_vods 경로 하나로 단일화한다.
        if existing_status in (
            "processing", "completed", "collecting", "analyzing",
            "transcribing", "chunking", "summarizing", "saving",
            "skipped_bootstrap",
            "error", "pending_retry",
        ):
            continue

        vod = parse_vod_info(raw, channel_id)
        new_vods.append(vod)
        logger.info(f"  새 VOD 감지: [{vod.video_no}] {vod.title} ({vod.duration}s)")

    if not new_vods:
        logger.info("  새 VOD 없음")

    state.update_poll_time()
    return new_vods
