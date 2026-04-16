"""A4 acquisition-followup: probe W5(11688000) and W4 offset(12702452 @1800s) chat feasibility.

Uses live pipeline.chat_collector.fetch_all_chats for W5 (relative ms from t=0).
For W4 offset, calls the Chzzk VOD chats API directly with playerMessageTime=1800000
and preserves absolute ms (no normalization), then filters to [1800s, 3600s).

Writes logs to sister work/<vod>/ only. No cookie usage required (public endpoint).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests

ROOT_LIVE = Path("C:/github/auto-caption-generator")
ROOT_SISTER = Path("C:/github/auto-caption-generator-main")

sys.path.insert(0, str(ROOT_LIVE))

from pipeline.chat_collector import fetch_all_chats, HEADERS  # noqa: E402
from pipeline.utils import sec_to_hms  # noqa: E402

W5_VOD = "11688000"
W4_VOD = "12702452"
W4_OFFSET_START_MS = 1_800_000
W4_OFFSET_END_MS = 3_600_000


def fetch_offset_chats(vod_id: str, start_ms: int, end_ms: int, fetch_delay: float = 1.0) -> list[dict]:
    """Pull chats for [start_ms, end_ms) without normalizing first-chat offset.

    Returns list of {'ms': absolute_ms, 'nick': str, 'msg': str, 'uid': str}.
    """
    chats: list[dict] = []
    next_time = str(start_ms)
    page = 0

    while True:
        url = (
            f"https://api.chzzk.naver.com/service/v1/videos"
            f"/{vod_id}/chats?playerMessageTime={next_time}"
        )
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 200:
            print(f"  API code={data.get('code')} at page {page}")
            break

        content = data.get("content", {})
        video_chats = content.get("videoChats", [])
        if not video_chats:
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
                except Exception:
                    pass
            chats.append({"ms": msg_time_ms, "nick": nick, "msg": content_text, "uid": uid})

        page += 1
        next_time = content.get("nextPlayerMessageTime")

        latest_ms = chats[-1]["ms"] if chats else start_ms
        if latest_ms >= end_ms:
            break
        if next_time is None:
            break

        time.sleep(fetch_delay)

    # filter window [start_ms, end_ms)
    filtered = [c for c in chats if start_ms <= c["ms"] < end_ms]
    return filtered


def save_absolute_chat_log(chats: list[dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for c in chats:
            ts = sec_to_hms(c["ms"] / 1000.0)
            f.write(f"[{ts}] {c['nick']}: {c['msg']}\n")


def probe_w5() -> dict:
    print(f"=== W5 probe: VOD {W5_VOD} chat (t=0..1800s) ===", flush=True)
    out_path = ROOT_SISTER / "work" / W5_VOD / f"{W5_VOD}_chat.log"
    try:
        chats = fetch_all_chats(W5_VOD, max_duration_sec=1800)
    except Exception as e:
        return {"status": "OTHER_FAIL", "error": f"{type(e).__name__}: {e}"}
    if not chats:
        return {"status": "NO_CHAT", "count": 0}
    coverage_sec = chats[-1]["ms"] / 1000.0
    # Save to sister (preserving normalized ms from fetch_all_chats)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for c in chats:
            ts = sec_to_hms(c["ms"] / 1000.0)
            f.write(f"[{ts}] {c['nick']}: {c['msg']}\n")
    return {
        "status": "OK",
        "count": len(chats),
        "coverage_sec": round(coverage_sec, 1),
        "density_msgs_per_min": round(len(chats) / max(coverage_sec / 60, 1e-9), 2),
        "out_path": str(out_path.relative_to(ROOT_SISTER)),
        "size_bytes": out_path.stat().st_size,
    }


def probe_w4_offset() -> dict:
    print(f"=== W4 offset probe: VOD {W4_VOD} chat (1800..3600s) ===", flush=True)
    out_path = ROOT_SISTER / "work" / W4_VOD / f"{W4_VOD}_chat_offset1800s.log"
    try:
        chats = fetch_offset_chats(W4_VOD, W4_OFFSET_START_MS, W4_OFFSET_END_MS)
    except Exception as e:
        return {"status": "OTHER_FAIL", "error": f"{type(e).__name__}: {e}"}
    if not chats:
        return {"status": "NO_CHAT", "count": 0, "start_ms": W4_OFFSET_START_MS, "end_ms": W4_OFFSET_END_MS}
    first_ms = chats[0]["ms"]
    last_ms = chats[-1]["ms"]
    save_absolute_chat_log(chats, out_path)
    return {
        "status": "OK",
        "count": len(chats),
        "first_ms": first_ms,
        "last_ms": last_ms,
        "coverage_sec": round((last_ms - first_ms) / 1000.0, 1),
        "density_msgs_per_min": round(len(chats) / max((last_ms - first_ms) / 60000.0, 1e-9), 2),
        "out_path": str(out_path.relative_to(ROOT_SISTER)),
        "size_bytes": out_path.stat().st_size,
    }


def main():
    print("a4_chat_probe: starting", flush=True)
    result_w5 = probe_w5()
    print(f"W5 result: {json.dumps(result_w5, ensure_ascii=False)}", flush=True)
    result_w4 = probe_w4_offset()
    print(f"W4 offset result: {json.dumps(result_w4, ensure_ascii=False)}", flush=True)
    summary = {"W5": result_w5, "W4_offset": result_w4}
    summary_path = ROOT_SISTER / "experiments" / "_a4_chat_probe_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"summary -> {summary_path}", flush=True)


if __name__ == "__main__":
    main()
