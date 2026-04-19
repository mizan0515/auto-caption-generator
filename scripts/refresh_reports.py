"""기존 output/*.html 리포트에 두 가지 패치를 in-place 적용.

1. `<script src="../../assets/vendor/chart.umd.min.js"></script>` 를
   Chart.js 본문 inline `<script>...</script>` 로 치환. output/ 에서 상대
   경로가 resolve 안돼서 채팅 밀도 차트가 안 보이던 문제를 해결.

2. "📄 원본 요약 마크다운 보기" <details> 또는 "📄 원본 요약 (구조화 파싱 실패)"
   card-body 의 최상단에 "🔗 퍼블리시된 웹페이지: <url>" 배너 주입.
   URL 은 사이드카 _metadata.json 의 video_no/streamer_id/channel_id/channel
   에서 파생한다.

멱등: 이미 패치된 파일은 스킵.

Usage:
    python scripts/refresh_reports.py
    python scripts/refresh_reports.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from html import escape as _html_escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.config import load_config, get_public_url_base, derive_streamer_id  # noqa: E402

CHART_ASSET = ROOT / "publish" / "web" / "assets" / "vendor" / "chart.umd.min.js"
OLD_SCRIPT_TAG = '<script src="../../assets/vendor/chart.umd.min.js"></script>'

PUBLISH_MARKER = 'class="publish-link"'


def _inline_script_tag() -> str:
    content = CHART_ASSET.read_text(encoding="utf-8")
    return f"<script>{content}</script>"


def _banner(report_url: str) -> str:
    url_esc = _html_escape(report_url)
    return (
        f'<div class="publish-link" style="margin-bottom:12px;padding:10px 14px;'
        f'background:var(--surface-2);border-left:3px solid var(--accent);'
        f'border-radius:6px;font-size:13px">'
        f'🔗 퍼블리시된 웹페이지: '
        f'<a href="{url_esc}" target="_blank" rel="noopener" '
        f'style="color:var(--accent);word-break:break-all">{url_esc}</a>'
        f'</div>'
    )


def _find_meta(html_path: Path) -> dict | None:
    stem = html_path.stem
    candidates = [
        html_path.with_name(f"{stem}_metadata.json"),
        html_path.with_name(f"{stem}_meta.json"),
    ]
    for p in candidates:
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
    return None


def _report_url(meta: dict, public_base: str) -> str | None:
    video_no = str(meta.get("video_no") or "").strip()
    if not video_no:
        return None
    sid = (meta.get("streamer_id") or "").strip()
    if not sid:
        sid = derive_streamer_id(
            meta.get("channel_id", "") or "",
            meta.get("channel", "") or meta.get("channel_name", "") or "",
        )
    return f"{public_base.rstrip('/')}/vod.html?v={video_no}&s={sid}"


# "📄 원본 요약 마크다운 보기" <details> 부모 card-body 시작 직후에 배너 삽입.
# pattern: `<div class="card"><div class="card-body"><details>...📄 원본 요약 마크다운 보기</summary>`
DETAILS_PAT = re.compile(
    r'(<div class="card"><div class="card-body">)(<details><summary[^>]*>📄 원본 요약 마크다운 보기</summary>)'
)
# 구조화 파싱 실패 카드
FALLBACK_PAT = re.compile(
    r'(<div class="card"><div class="card-head"><h2>📄 원본 요약 \(구조화 파싱 실패\)</h2></div>\s*<div class="card-body">)(<div class="notes">)'
)


def patch_html(text: str, report_url: str | None, inline_script: str) -> tuple[str, list[str]]:
    changes: list[str] = []

    if OLD_SCRIPT_TAG in text:
        text = text.replace(OLD_SCRIPT_TAG, inline_script, 1)
        changes.append("chart-inline")

    if report_url and PUBLISH_MARKER not in text:
        banner = _banner(report_url)
        new_text, n = DETAILS_PAT.subn(rf"\1{banner}\2", text, count=1)
        if n == 0:
            new_text, n = FALLBACK_PAT.subn(rf"\1{banner}\2", text, count=1)
        if n:
            text = new_text
            changes.append("publish-banner")

    return text, changes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--output-dir", default=None)
    args = ap.parse_args()

    cfg = load_config()
    out_dir = Path(args.output_dir or cfg.get("output_dir", "./output"))
    public_base = get_public_url_base(cfg)
    if not public_base:
        print("경고: publish_public_url_base / publish_cloudflare_project 미설정 — URL 배너 생략")

    if not CHART_ASSET.exists():
        print(f"오류: chart.js 자산 없음: {CHART_ASSET}", file=sys.stderr)
        return 2
    inline_script = _inline_script_tag()

    html_files = sorted(out_dir.glob("*.html"))
    if not html_files:
        print(f"대상 HTML 없음: {out_dir}")
        return 0

    total_patched = 0
    for hp in html_files:
        meta = _find_meta(hp)
        report_url = _report_url(meta, public_base) if (meta and public_base) else None

        try:
            text = hp.read_text(encoding="utf-8")
        except OSError as e:
            print(f"  읽기 실패: {hp.name} ({e})")
            continue

        new_text, changes = patch_html(text, report_url, inline_script)
        if not changes:
            print(f"  skip (이미 패치됨): {hp.name}")
            continue

        if args.dry_run:
            print(f"  [DRY] patch {changes}: {hp.name}")
        else:
            hp.write_text(new_text, encoding="utf-8")
            print(f"  patched {changes}: {hp.name}")
        total_patched += 1

    print(f"\n총 {total_patched}/{len(html_files)} 개 패치됨")
    return 0


if __name__ == "__main__":
    sys.exit(main())
