import argparse
import math
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from content.network import NetworkManager
from pipeline.config import get_cookies, load_config, validate_cookies
from pipeline.main import run_single


def main() -> int:
    parser = argparse.ArgumentParser(description="Process one VOD in fixed-duration slices.")
    parser.add_argument("video_no")
    parser.add_argument("--slice-sec", type=int, default=3600)
    parser.add_argument("--start-offset", type=int, default=0)
    parser.add_argument("--config", type=str, default=None)
    parser.add_argument("--claude-model", type=str, default=None)
    args = parser.parse_args()

    cfg = load_config(config_path=args.config)
    if args.claude_model is not None:
        cfg["claude_model"] = args.claude_model

    if not validate_cookies(cfg):
        return 2

    cookies = get_cookies(cfg)
    _, _, _, _, _, metadata = NetworkManager.get_video_info(args.video_no, cookies)
    duration = int(metadata.get("duration", 0))
    if duration <= 0:
        print(f"duration lookup failed for {args.video_no}", file=sys.stderr)
        return 2

    slice_sec = max(1, args.slice_sec)
    offsets = list(range(max(0, args.start_offset), duration, slice_sec))
    total_parts = len(offsets)

    for index, offset in enumerate(offsets, start=1):
        part_duration = min(slice_sec, duration - offset)
        print(
            f"[{index}/{total_parts}] video={args.video_no} "
            f"offset={offset}s duration={part_duration}s"
        )
        run_single(
            args.video_no,
            cfg,
            limit_duration_sec=part_duration,
            start_offset_sec=offset,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
