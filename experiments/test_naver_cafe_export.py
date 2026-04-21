"""Verify that report HTML includes the Naver Cafe export card and template."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.models import VODInfo
from pipeline.summarizer import _generate_html


ROOT = Path(__file__).resolve().parent.parent
MD_PATH = ROOT / "output" / "12702452_20260412_7시 인생게임 (w. 지누,뿡,똘복) 인생에 프로란 없다. 모두 아마추어다. ٩(●'▿'●)۶.md"
META_PATH = ROOT / "output" / "12702452_20260412_7시 인생게임 (w. 지누,뿡,똘복) 인생에 프로란 없다. 모두 아마추어다. ٩(●'▿'●)۶_metadata.json"
OUT_PATH = ROOT / "output" / "12702452_naver_export_preview.html"


def main() -> int:
    md = MD_PATH.read_text(encoding="utf-8")
    meta = json.loads(META_PATH.read_text(encoding="utf-8"))

    vod = VODInfo(
        video_no="12702452",
        title="7시 인생게임 (w. 지누,뿡,똘복) 인생에 프로란 없다. 모두 아마추어다. ٩(●'▿'●)۶",
        channel_id="a7e175625fdea5a7d98428302b7aa57f",
        channel_name="수피",
        duration=20552,
        publish_date="2026-04-12T18:35:23+09:00",
        category="인생게임",
    )

    fake_chats = [
        {"ms": int(h["sec"] * 1000), "msg": "테스트", "nick": "test", "uid": "x"}
        for h in meta.get("highlights", [])
    ]

    html = _generate_html(
        md,
        vod,
        meta.get("highlights", [])[:10],
        fake_chats,
        community_posts=[],
        public_url_base="https://auto-caption-generator-site.pages.dev",
    )
    OUT_PATH.write_text(html, encoding="utf-8")

    required_tokens = [
        "네이버 카페 붙여넣기",
        "copyNaverCafeHtml",
        "naverCafeTemplate",
        "🔗 요약 웹페이지:",
        "📝 에디터의 방송 후기",
    ]
    missing = [token for token in required_tokens if token not in html]
    if missing:
        print("Missing tokens:", missing)
        return 1

    print(f"Rendered to {OUT_PATH}")
    print(f"Verified token count: {len(required_tokens)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
