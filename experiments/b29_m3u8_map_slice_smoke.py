import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.config import get_cookies, load_config
from pipeline.downloader import download_vod_144p
from split_video import get_duration


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("video_no")
    parser.add_argument("--start-sec", type=int, default=0)
    parser.add_argument("--duration-sec", type=int, default=300)
    args = parser.parse_args()

    cfg = load_config()
    cookies = get_cookies(cfg)
    out_dir = Path("work") / f"{args.video_no}_m3u8_smoke"
    out_dir.mkdir(parents=True, exist_ok=True)

    path = download_vod_144p(
        args.video_no,
        cookies,
        str(out_dir),
        start_sec=args.start_sec,
        duration_sec=args.duration_sec,
        filename_suffix="_m3u8_smoke",
    )
    duration = get_duration(path)
    print(f"PASS: {args.video_no} slice duration={duration:.2f}s")


if __name__ == "__main__":
    main()
