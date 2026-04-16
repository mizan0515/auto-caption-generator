"""W4 offset re-probe: pull 12702452 chat through 3600s using fetch_all_chats (paginated
from t=0) and filter to [1800, 3600) window post-normalization.

If chat exists past 1800s, save as work/12702452/12702452_chat_offset1800s.log (normalized).
Also report full-window density for comparison with the existing 0-1799s log.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT_LIVE = Path("C:/github/auto-caption-generator")
ROOT_SISTER = Path("C:/github/auto-caption-generator-main")
sys.path.insert(0, str(ROOT_LIVE))

from pipeline.chat_collector import fetch_all_chats  # noqa: E402
from pipeline.utils import sec_to_hms  # noqa: E402

VOD = "12702452"
WIN_START_MS = 1_800_000
WIN_END_MS = 3_600_000


def main():
    print(f"fetch_all_chats({VOD}, max_duration_sec=3600) paginating", flush=True)
    chats = fetch_all_chats(VOD, max_duration_sec=3600)
    print(f"total fetched: {len(chats)}", flush=True)
    if chats:
        last_ms = chats[-1]["ms"]
        print(f"last normalized ms: {last_ms} ({sec_to_hms(last_ms/1000)})", flush=True)
    window = [c for c in chats if WIN_START_MS <= c["ms"] < WIN_END_MS]
    print(f"window [1800,3600) count: {len(window)}", flush=True)
    result = {
        "vod": VOD,
        "total_fetched_le_3600s": len(chats),
        "last_normalized_ms": chats[-1]["ms"] if chats else None,
        "window_1800_3600_count": len(window),
    }
    if window:
        first_ms = window[0]["ms"]
        last_ms = window[-1]["ms"]
        out_path = ROOT_SISTER / "work" / VOD / f"{VOD}_chat_offset1800s.log"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as f:
            for c in window:
                # write timestamps as offset-from-1800s so the chunker sees [00:00, 30:00)
                rel_ms = c["ms"] - WIN_START_MS
                ts = sec_to_hms(rel_ms / 1000.0)
                f.write(f"[{ts}] {c['nick']}: {c['msg']}\n")
        result.update({
            "status": "OK",
            "window_first_ms": first_ms,
            "window_last_ms": last_ms,
            "window_coverage_sec": round((last_ms - first_ms) / 1000.0, 1),
            "window_density_msgs_per_min": round(len(window) / max((last_ms - first_ms) / 60000.0, 1e-9), 2),
            "out_path": str(out_path.relative_to(ROOT_SISTER)),
            "size_bytes": out_path.stat().st_size,
        })
    else:
        result["status"] = "NO_CHAT_IN_WINDOW"
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    Path(ROOT_SISTER / "experiments" / "_a4_chat_probe2_summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
