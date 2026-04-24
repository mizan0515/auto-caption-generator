from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.summarizer import _parse_summary_sections  # noqa: E402
from pipeline.timeline_alignment import (  # noqa: E402
    build_offset_profile,
    pick_anchor_candidates,
    remap_sections,
    render_youtube_comment_text,
)


def main() -> int:
    report_path = ROOT / "site" / "vods" / "12878342" / "report.md"
    meta_path = ROOT / "site" / "vods" / "12878342" / "metadata.json"
    report_md = report_path.read_text(encoding="utf-8")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    sec = _parse_summary_sections(report_md)
    source_duration = int(meta["duration"])
    youtube_duration = 37002

    profile = build_offset_profile(source_duration, youtube_duration)
    remapped = remap_sections(sec, profile)
    text = render_youtube_comment_text(remapped, profile, compact=False)
    candidates = pick_anchor_candidates(sec)

    print(f"source_duration={source_duration}")
    print(f"youtube_duration={youtube_duration}")
    print(f"offset_sec={source_duration - youtube_duration}")
    print(f"first_timeline_src={sec['timeline'][0]['tc']}")
    print(f"first_timeline_dst={remapped['timeline'][0]['tc']}")
    print(f"timeline_count={len(remapped['timeline'])}")
    print(f"anchor_candidates={len(candidates)}")
    print("---")
    for line in text.splitlines()[:8]:
        print(line.encode("cp949", errors="replace").decode("cp949"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
