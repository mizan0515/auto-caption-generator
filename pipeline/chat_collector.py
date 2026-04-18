"""Chzzk VOD 채팅 리플레이 수집 (chzzk_editor.py 로직 기반)"""

import json
import logging
import time

import requests

from .utils import retry

logger = logging.getLogger("pipeline")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

FETCH_DELAY = 1.0  # 페이지별 대기 시간(초)


def fetch_all_chats(
    vod_id: str,
    fetch_delay: float = FETCH_DELAY,
    max_duration_sec: int = 0,
) -> list[dict]:
    """
    Chzzk API에서 VOD 채팅 전체를 수집.
    각 항목: {'ms': int, 'nick': str, 'msg': str, 'uid': str}
    ms는 영상 시작 기준 상대 시간(밀리초).

    Args:
        max_duration_sec: >0 이면 이 시간(초) 까지의 채팅만 수집. 이후 페이지는 스킵.
    """
    chats = []
    next_time = "0"
    page = 0

    if max_duration_sec > 0:
        logger.info(f"채팅 수집 시작: VOD {vod_id} (제한 시간: {max_duration_sec}초)")
    else:
        logger.info(f"채팅 수집 시작: VOD {vod_id}")

    while True:
        url = (
            f"https://api.chzzk.naver.com/service/v1/videos"
            f"/{vod_id}/chats?playerMessageTime={next_time}"
        )
        try:
            resp = requests.get(url, headers=HEADERS, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            logger.warning(f"채팅 API 요청 오류: {e}")
            if page == 0:
                return []
            break
        except json.JSONDecodeError:
            logger.warning("채팅 API JSON 파싱 오류")
            break

        if data.get("code") != 200:
            logger.warning(f"채팅 API 응답 오류: code={data.get('code')}")
            break

        content = data.get("content", {})
        video_chats = content.get("videoChats", [])

        if not video_chats:
            logger.info(f"채팅 수집 완료: 총 {len(chats):,}개 (마지막 페이지)")
            break

        for chat in video_chats:
            msg_time_ms = chat.get("messageTime", 0)
            content_text = chat.get("content", "")
            uid = chat.get("userIdHash", "")

            nick = "Unknown"
            profile_raw = chat.get("profile")
            if profile_raw and profile_raw != "null":
                try:
                    profile = json.loads(profile_raw)
                    nick = profile.get("nickname", "Unknown")
                except (json.JSONDecodeError, TypeError, AttributeError):
                    pass

            chats.append({
                "ms": msg_time_ms,
                "nick": nick,
                "msg": content_text,
                "uid": uid,
            })

        page += 1
        next_time = content.get("nextPlayerMessageTime")

        if page % 10 == 0:
            offset = chats[0]["ms"] if chats else 0
            total_sec = (chats[-1]["ms"] - offset) / 1000 if chats else 0
            from .utils import sec_to_hms
            logger.info(f"  채팅 수집 중: 페이지 {page}, 누적 {len(chats):,}개, 위치 {sec_to_hms(total_sec)}")

        # 시간 제한 체크 (테스트 모드)
        if max_duration_sec > 0 and chats:
            offset_ms = chats[0]["ms"]
            latest_sec = (chats[-1]["ms"] - offset_ms) / 1000
            if latest_sec >= max_duration_sec:
                logger.info(
                    f"채팅 수집 완료 (시간 제한 도달: {latest_sec:.0f}s ≥ {max_duration_sec}s): "
                    f"총 {len(chats):,}개"
                )
                break

        if next_time is None:
            logger.info(f"채팅 수집 완료: 총 {len(chats):,}개")
            break

        time.sleep(fetch_delay)

    # 첫 채팅 기준 상대 시간 정규화
    if chats:
        offset_ms = chats[0]["ms"]
        for chat in chats:
            chat["ms"] = max(0, chat["ms"] - offset_ms)

    # 시간 제한 필터링 (한 페이지 안에 임계치 넘는 메시지가 섞여있을 수 있음)
    if max_duration_sec > 0 and chats:
        limit_ms = max_duration_sec * 1000
        before = len(chats)
        chats = [c for c in chats if c["ms"] <= limit_ms]
        if len(chats) < before:
            logger.info(f"  채팅 시간 필터: {before}개 → {len(chats)}개 (≤ {max_duration_sec}s)")

    return chats


def save_chat_log(chats: list[dict], output_path: str) -> str:
    """채팅 로그를 텍스트 파일로 저장.

    텍스트(.log) 는 사람이 읽기 좋은 포맷, 사이드카 JSON(.log.json) 은
    재시도 시 무손실 재로드용. 두 개를 원자적으로 같이 쓴다.
    """
    from .utils import sec_to_hms
    with open(output_path, "w", encoding="utf-8") as f:
        for chat in chats:
            ts = sec_to_hms(chat["ms"] / 1000.0)
            f.write(f"[{ts}] {chat['nick']}: {chat['msg']}\n")

    json_path = output_path + ".json"
    tmp = json_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(chats, f, ensure_ascii=False)
    import os as _os
    _os.replace(tmp, json_path)

    logger.info(f"채팅 로그 저장: {output_path} ({len(chats):,}개, JSON 사이드카 포함)")
    return output_path


def load_chat_log_json(video_no: str, work_dir: str) -> list[dict] | None:
    """save_chat_log 이 남긴 사이드카 JSON 을 로드. 없으면 None.

    RESUME 용: 재시도 시 API 재호출 (수 분 ~ 수십 분) 을 피하기 위해 사용.
    """
    import os as _os
    json_path = _os.path.join(work_dir, f"{video_no}_chat.log.json")
    if not _os.path.isfile(json_path) or _os.path.getsize(json_path) == 0:
        return None
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return data
        logger.warning(f"채팅 JSON 형식 이상 → 재수집: {json_path}")
        return None
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"채팅 JSON 로드 실패 → 재수집: {e}")
        return None
