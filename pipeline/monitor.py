"""Chzzk VOD 목록 폴링 — 새 다시보기 감지"""

import logging
import re
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
    return VODInfo(
        video_no=str(raw.get("videoNo", "")),
        title=raw.get("videoTitle", "제목 없음"),
        channel_id=channel_id,
        channel_name=raw.get("channel", {}).get("channelName", ""),
        duration=raw.get("duration", 0),
        publish_date=raw.get("liveOpenDate", raw.get("publishDate", "")),
        thumbnail_url=raw.get("thumbnailImageUrl", ""),
        category=raw.get("videoCategoryValue", ""),
    )


def check_new_vods(
    channel_id: str,
    cookies: dict,
    state: PipelineState,
    page: int = 0,
    size: int = 20,
) -> list[VODInfo]:
    """새로운 VOD 감지. 이미 처리된/처리중인 VOD는 제외."""
    logger.info(f"VOD 목록 폴링: 채널 {channel_id[:8]}...")
    try:
        raw_list = fetch_vod_list(channel_id, cookies, page, size)
    except requests.RequestException as e:
        logger.error(f"VOD 목록 조회 실패: {e}")
        return []

    new_vods = []
    for raw in raw_list:
        video_no = str(raw.get("videoNo", ""))
        if not video_no:
            continue

        existing_status = state.get_status(video_no)
        if existing_status in ("processing", "completed"):
            continue

        vod = parse_vod_info(raw, channel_id)
        new_vods.append(vod)
        logger.info(f"  새 VOD 감지: [{vod.video_no}] {vod.title} ({vod.duration}s)")

    if not new_vods:
        logger.info("  새 VOD 없음")

    state.update_poll_time()
    return new_vods
