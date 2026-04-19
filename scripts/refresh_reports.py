"""기존 output/ 리포트(.md, .html) 에 공유 링크 + OG 미리보기 패치를 in-place 적용.

각 리포트에 다음을 적용:

1. .md 최상단에 "🔗 요약 웹페이지" + "▶️ 치지직 다시보기" 링크 2줄 prepend
2. .html 의 구 `publish-link` 배너 div 제거 (있으면) — 이제 마크다운 본문 안에
   링크가 들어있어 중복 제거
3. .html `<head>` 에 OG/Twitter 메타 태그 추가 (SNS 미리보기)
4. .html 의 마크다운 렌더 본문 최상단에 공유 링크를 `<p><strong>...</strong> <a>` 형식으로 주입
5. chart.umd.min.js → inline script (이미 적용돼 있으면 스킵)

멱등: 이미 패치된 파일은 건드리지 않는다.

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

from pipeline.config import load_config, get_public_url_base  # noqa: E402

CHART_ASSET = ROOT / "publish" / "web" / "assets" / "vendor" / "chart.umd.min.js"
OLD_SCRIPT_TAG = '<script src="../../assets/vendor/chart.umd.min.js"></script>'

OLD_PUBLISH_LINK_PAT = re.compile(
    r'<div class="publish-link"[^>]*>.*?</div>', re.DOTALL
)
OG_PROBE = 'property="og:title"'
HEADER_LINK_PROBE = "🔗 요약 웹페이지"


def _inline_script_tag() -> str:
    return f"<script>{CHART_ASSET.read_text(encoding='utf-8')}</script>"


def _find_meta(html_path: Path) -> dict | None:
    stem = html_path.stem
    for suffix in ("_metadata.json", "_meta.json"):
        p = html_path.with_name(f"{stem}{suffix}")
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
    return None


def _report_url(meta: dict, public_base: str) -> str | None:
    video_no = str(meta.get("video_no") or "").strip()
    if not video_no or not public_base:
        return None
    return f"{public_base.rstrip('/')}/vods/{video_no}/report"


def _chzzk_url(meta: dict) -> str | None:
    vno = str(meta.get("video_no") or "").strip()
    return f"https://chzzk.naver.com/video/{vno}" if vno else None


def _md_prepend(md_path: Path, report_url: str | None, chzzk_url: str | None,
                dry_run: bool) -> bool:
    if not md_path.exists():
        return False
    text = md_path.read_text(encoding="utf-8")
    if HEADER_LINK_PROBE in text:
        return False
    lines = []
    if report_url:
        lines.append(f"- **🔗 요약 웹페이지:** [{report_url}]({report_url})")
    if chzzk_url:
        lines.append(f"- **▶️ 치지직 다시보기:** [{chzzk_url}]({chzzk_url})")
    if not lines:
        return False
    new = "\n".join(lines) + "\n\n" + text
    if not dry_run:
        md_path.write_text(new, encoding="utf-8")
    return True


def _build_og_meta(meta: dict, md_text: str, report_url: str | None) -> str:
    title_raw = (meta.get("title") or "").strip()
    channel = (meta.get("channel") or "").strip()
    title = f"{title_raw} — 방송 분석 리포트"
    if channel:
        title = f"[{channel}] {title}"

    # description: 첫 200자에서 뽑는다 (hashtags/quote 추출은 md 파싱 필요 → 단순화)
    desc_src = md_text
    # 기존에 prepend 된 링크가 있으면 건너뛰고 실제 summary 시작 위치부터
    if HEADER_LINK_PROBE in desc_src:
        # skip past the two bullet lines
        for _ in range(2):
            nl = desc_src.find("\n")
            if nl == -1:
                break
            desc_src = desc_src[nl + 1:]
        desc_src = desc_src.lstrip()
    description = desc_src.replace("\n", " ").strip()
    # 마크다운 마커 정리
    description = re.sub(r"[#*`>\-]+", " ", description)
    description = re.sub(r"\s+", " ", description).strip()
    if len(description) > 300:
        description = description[:297] + "..."

    thumbnail = (meta.get("thumbnail_url") or "").strip() or None
    card_type = "summary_large_image" if thumbnail else "summary"

    tags = [
        '<meta property="og:type" content="article">',
        '<meta property="og:site_name" content="auto-caption-generator">',
        f'<meta property="og:title" content="{_html_escape(title)}">',
        f'<meta property="og:description" content="{_html_escape(description)}">',
    ]
    if report_url:
        tags.append(f'<meta property="og:url" content="{_html_escape(report_url)}">')
    if thumbnail:
        tags.append(f'<meta property="og:image" content="{_html_escape(thumbnail)}">')
    tags.append(f'<meta name="twitter:card" content="{card_type}">')
    tags.append(f'<meta name="twitter:title" content="{_html_escape(title)}">')
    tags.append(f'<meta name="twitter:description" content="{_html_escape(description)}">')
    if thumbnail:
        tags.append(f'<meta name="twitter:image" content="{_html_escape(thumbnail)}">')
    return "\n".join(tags)


def _body_link_paragraph(report_url: str | None, chzzk_url: str | None) -> str:
    """fallback_html 본문 최상단에 주입할 `<p>` 링크 단락."""
    parts = []
    if report_url:
        parts.append(
            f'<strong>🔗 요약 웹페이지:</strong> '
            f'<a href="{_html_escape(report_url)}" target="_blank" rel="noopener" '
            f'style="color:var(--accent);word-break:break-all">{_html_escape(report_url)}</a>'
        )
    if chzzk_url:
        parts.append(
            f'<strong>▶️ 치지직 다시보기:</strong> '
            f'<a href="{_html_escape(chzzk_url)}" target="_blank" rel="noopener" '
            f'style="color:var(--accent);word-break:break-all">{_html_escape(chzzk_url)}</a>'
        )
    if not parts:
        return ""
    # 여러 줄을 하나의 p 안에 <br> 로 이어붙임 (구조 단순화)
    return "<p>" + "<br>".join(parts) + "</p>"


# 기존 구조: <div class="notes" style="margin-top:16px"><p>...</p></div>  (details 안)
# 또는:     <div class="notes"><p>...</p></div>  (fallback 카드)
NOTES_OPEN_PAT = re.compile(
    r'(<div class="notes"(?: style="[^"]*")?>)<p>',
)


def patch_html(html_text: str, meta: dict, public_base: str,
               inline_script: str, md_text: str) -> tuple[str, list[str]]:
    changes: list[str] = []

    report_url = _report_url(meta, public_base)
    chzzk_url = _chzzk_url(meta)

    # 1. chart.js inline (기존 패치)
    if OLD_SCRIPT_TAG in html_text:
        html_text = html_text.replace(OLD_SCRIPT_TAG, inline_script, 1)
        changes.append("chart-inline")

    # 2. 구 publish-link 배너 제거
    new_text, n = OLD_PUBLISH_LINK_PAT.subn("", html_text)
    if n:
        html_text = new_text
        changes.append("remove-old-banner")

    # 3. OG 메타태그 삽입
    if OG_PROBE not in html_text:
        og_meta = _build_og_meta(meta, md_text, report_url)
        # <title>...</title> 바로 다음에 삽입 — <head> 끝 찾기보다 안전
        html_text = re.sub(
            r"(</title>)",
            r"\1\n" + og_meta.replace("\\", "\\\\"),
            html_text,
            count=1,
        )
        changes.append("og-meta")

    # 4. 본문 최상단에 링크 단락 주입
    if HEADER_LINK_PROBE not in html_text:
        link_p = _body_link_paragraph(report_url, chzzk_url)
        if link_p:
            new_text, n = NOTES_OPEN_PAT.subn(r"\1" + link_p + "<p>", html_text, count=1)
            if n:
                html_text = new_text
                changes.append("body-links")

    return html_text, changes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--output-dir", default=None)
    args = ap.parse_args()

    cfg = load_config()
    out_dir = Path(args.output_dir or cfg.get("output_dir", "./output"))
    public_base = get_public_url_base(cfg)
    if not public_base:
        print("경고: publish URL base 미설정 — 링크/OG URL 생략")

    if not CHART_ASSET.exists():
        print(f"오류: chart.js 자산 없음: {CHART_ASSET}", file=sys.stderr)
        return 2
    inline_script = _inline_script_tag()

    html_files = sorted(out_dir.glob("*.html"))
    if not html_files:
        print(f"대상 HTML 없음: {out_dir}")
        return 0

    total_changed = 0
    for hp in html_files:
        meta = _find_meta(hp)
        if not meta:
            print(f"  skip (metadata 없음): {hp.name}")
            continue

        md_path = hp.with_suffix(".md")
        md_changed = _md_prepend(md_path, _report_url(meta, public_base), _chzzk_url(meta), args.dry_run)
        md_text_now = md_path.read_text(encoding="utf-8") if md_path.exists() else ""

        try:
            html_text = hp.read_text(encoding="utf-8")
        except OSError as e:
            print(f"  읽기 실패: {hp.name} ({e})")
            continue

        new_html, changes = patch_html(html_text, meta, public_base, inline_script, md_text_now)
        if md_changed:
            changes = ["md-prepend"] + changes

        if not changes:
            print(f"  skip (이미 패치됨): {hp.name}")
            continue

        if args.dry_run:
            print(f"  [DRY] {changes}: {hp.name}")
        else:
            hp.write_text(new_html, encoding="utf-8")
            print(f"  patched {changes}: {hp.name}")
        total_changed += 1

    print(f"\n총 {total_changed}/{len(html_files)} 개 변경됨")
    return 0


if __name__ == "__main__":
    sys.exit(main())
