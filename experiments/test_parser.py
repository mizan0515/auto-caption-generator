"""HTML 파서 검증 스크립트"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.summarizer import _parse_summary_sections

MD_PATH = Path(__file__).resolve().parent.parent / "output" / "12702452_20260412_7시 인생게임 (w. 지누,뿡,똘복) 인생에 프로란 없다. 모두 아마추어다. ٩(●'▿'●)۶.md"

with open(MD_PATH, "r", encoding="utf-8") as f:
    md = f.read()

sec = _parse_summary_sections(md)

OUT = Path(__file__).resolve().parent / "parser_test_output.txt"
with open(OUT, "w", encoding="utf-8") as f:
    f.write(f"title: {sec['title']}\n")
    f.write(f"hashtags: {sec['hashtags']}\n")
    f.write(f"pull_quote: {sec['pull_quote']}\n\n")
    f.write(f"timeline entries: {len(sec['timeline'])}\n")
    for t in sec["timeline"]:
        f.write(f"  [{t['tc']}] {t['title']} | mood={t['mood']} ({t['mood_raw']})\n")
        f.write(f"      summary: {t['summary'][:80]}\n")
        f.write(f"      evidence: {t['evidence'][:80]}\n")
    f.write(f"\nhighlights: {len(sec['highlights'])}\n")
    for h in sec["highlights"]:
        f.write(f"  [{h['tc_range']}] {h['title']}\n      reason: {h['reason']}\n")
    f.write(f"\neditor notes paragraphs: {len(sec['editor_notes'])}\n")
    for i, p in enumerate(sec["editor_notes"]):
        f.write(f"  [{i}] {p[:100]}...\n")

print(f"Wrote test output to {OUT}")
