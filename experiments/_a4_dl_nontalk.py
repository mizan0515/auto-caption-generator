"""Download one non-game VOD to sister work/ via pipeline.downloader.download_vod_144p.

Reads cookies from live pipeline_config.json. Writes only to sister work/<video_no>/.
Does NOT touch live work/.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.downloader import download_vod_144p

CONFIG_PATH = Path("C:/github/auto-caption-generator/pipeline_config.json")
SISTER_WORK = Path("C:/github/auto-caption-generator-main/work")

VIDEO_NO = "11688000"  # Winter Olympics category (non-game axis)

def main():
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    cookies = {"NID_AUT": cfg.get("NID_AUT", ""), "NID_SES": cfg.get("NID_SES", "")}
    out_dir = SISTER_WORK / VIDEO_NO
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[dl] target={VIDEO_NO} out_dir={out_dir}", flush=True)

    def progress(pct, downloaded, total):
        # print occasional progress, not per-chunk
        pass

    path = download_vod_144p(VIDEO_NO, cookies, str(out_dir), progress_func=None)
    print(f"[dl] DONE path={path}", flush=True)
    return 0

if __name__ == "__main__":
    sys.exit(main())
