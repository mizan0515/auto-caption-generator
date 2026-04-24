import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.scraper import load_manual_community_posts


def main():
    with tempfile.TemporaryDirectory() as td:
        work_dir = Path(td)
        video_no = "12890507"
        path = work_dir / f"{video_no}_community.manual.json"
        payload = [
            {
                "title": "테스트 글",
                "url": "https://www.fmkorea.com/123",
                "body_preview": "본문 미리보기",
                "author": "작성자",
                "timestamp": "2026.04.25 02:03",
                "views": 100,
                "comments": 5,
                "likes": 2,
            }
        ]
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        posts = load_manual_community_posts(video_no, str(work_dir))
        assert posts is not None
        assert len(posts) == 1
        assert posts[0].title == "테스트 글"
        assert posts[0].url == "https://www.fmkorea.com/123"
        print("manual community override ok")


if __name__ == "__main__":
    main()
