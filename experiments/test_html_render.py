"""새 _generate_html() 로 기존 MD를 렌더링하여 실제 HTML 출력 확인"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.summarizer import _generate_html
from pipeline.models import VODInfo

MD_PATH = Path(__file__).resolve().parent.parent / "output" / "12702452_20260412_7시 인생게임 (w. 지누,뿡,똘복) 인생에 프로란 없다. 모두 아마추어다. ٩(●'▿'●)۶.md"
OUT_PATH = Path(__file__).resolve().parent.parent / "output" / "12702452_rendered_preview.html"

with open(MD_PATH, "r", encoding="utf-8") as f:
    md = f.read()

vod = VODInfo(
    video_no="12702452",
    title="7시 인생게임 (w. 지누,뿡,똘복) 인생에 프로란 없다. 모두 아마추어다. ٩(●'▿'●)۶",
    channel_id="a7e175625fdea5a7d98428302b7aa57f",
    channel_name="탬탬버린",
    duration=20552,
    publish_date="2026-04-12T18:35:23+09:00",
    category="인생게임",
)

# chats 샘플 (차트용): 메타데이터 JSON에서 가져오기
import json
meta_path = MD_PATH.parent / (MD_PATH.stem + "_metadata.json")
with open(meta_path, "r", encoding="utf-8") as f:
    meta = json.load(f)

# 차트용 간단 chats 시뮬레이션 (실제 파이프라인에선 실제 chats 전달됨)
fake_chats = [{"ms": int(h["sec"] * 1000), "msg": "ㅋㅋ", "nick": "test", "uid": "x"} for h in meta.get("highlights", [])]

html = _generate_html(md, vod, meta.get("highlights", [])[:10], fake_chats, community_posts=[])

with open(OUT_PATH, "w", encoding="utf-8") as f:
    f.write(html)

print(f"Rendered to {OUT_PATH}")
print(f"Size: {len(html):,} chars")
