"""Enumerate channel VOD list to classify by category for A4 genre acquisition.

Reads cookies + target_channel_id from LIVE pipeline_config.json only.
Writes NOTHING to disk. Prints per-VOD summary (video_no, category, duration, title).
"""
import json
import sys
import os
from pathlib import Path

# Ensure sister pipeline is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.monitor import fetch_vod_list

CONFIG_PATH = Path("C:/github/auto-caption-generator/pipeline_config.json")

def main():
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    cookies = {
        "NID_AUT": cfg.get("NID_AUT", ""),
        "NID_SES": cfg.get("NID_SES", ""),
    }
    channel_id = cfg.get("target_channel_id", "")
    if not channel_id:
        print("NO_CHANNEL_ID", flush=True)
        return 2

    print(f"CHANNEL={channel_id[:8]}...", flush=True)

    rows = []
    for page in (0, 1, 2):
        vids = fetch_vod_list(channel_id, cookies, page=page, size=20)
        for v in vids:
            rows.append({
                "video_no": str(v.get("videoNo", "")),
                "category": v.get("videoCategoryValue", ""),
                "category_type": v.get("videoCategoryType", ""),
                "duration": v.get("duration", 0),
                "title": v.get("videoTitle", "")[:60],
            })
        if len(vids) < 20:
            break

    print(f"TOTAL={len(rows)}", flush=True)
    # Sort by category, print
    by_cat = {}
    for r in rows:
        by_cat.setdefault(r["category"] or "(empty)", []).append(r)
    for cat, items in by_cat.items():
        print(f"--- category: {cat} ({len(items)}) ---", flush=True)
        for r in items:
            print(f"  {r['video_no']:>10} | dur={r['duration']:>6}s | {r['title']}", flush=True)
    return 0

if __name__ == "__main__":
    sys.exit(main())
