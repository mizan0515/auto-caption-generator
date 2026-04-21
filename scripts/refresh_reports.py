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
from pipeline.models import VODInfo  # noqa: E402
from pipeline.summarizer import (  # noqa: E402
    _postprocess_summary_md,
    _parse_summary_sections,
    _render_naver_cafe_html,
    _render_chzzk_comment_text,
)

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


def _strip_old_top_links(md: str) -> str:
    """이전 마이그레이션이 최상단에 prepend 한 2줄 링크 블록 제거.

    패턴: "- **🔗 요약 웹페이지:** ..." 및/또는 "- **▶️ 치지직 다시보기:** ..."
    가 파일 시작에 있고 빈 줄로 끝나면 걷어낸다.
    """
    lines = md.splitlines(keepends=True)
    removed = 0
    i = 0
    while i < len(lines):
        stripped = lines[i].lstrip()
        if stripped.startswith("- **🔗 요약 웹페이지:") or stripped.startswith("- **▶️ 치지직 다시보기:"):
            i += 1
            removed += 1
            continue
        break
    if removed == 0:
        return md
    # 빈 줄 하나까지 소모
    while i < len(lines) and lines[i].strip() == "":
        i += 1
        break
    return "".join(lines[i:])


def _md_migrate(md_path: Path, vod_info: VODInfo, public_base: str,
                dry_run: bool) -> tuple[bool, str]:
    """기존 .md 를 마이그레이션하고 새로운 텍스트를 반환.

    Returns: (changed, new_text)
    """
    if not md_path.exists():
        return False, ""
    text = md_path.read_text(encoding="utf-8")
    original = text
    # 구 top-prepend 제거 → postprocess 로 리포트 헤더 아래에 재삽입 + 하이라이트 정돈
    text = _strip_old_top_links(text)
    text = _postprocess_summary_md(text, vod_info, public_base)
    if text == original:
        return False, original
    if not dry_run:
        md_path.write_text(text, encoding="utf-8")
    return True, text


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


def _render_fallback_body(md: str) -> str:
    """_generate_html 의 raw markdown fallback 본문 렌더링 재사용용 헬퍼."""
    body = _html_escape(md)
    body = re.sub(r"^###\s+(.+)$", r"<h3>\1</h3>", body, flags=re.M)
    body = re.sub(r"^##\s+(.+)$", r"<h2>\1</h2>", body, flags=re.M)
    body = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", body)
    body = re.sub(
        r'\[([^\]]+)\]\((https?://[^)\s]+)\)',
        r'<a href="\2" target="_blank" rel="noopener" style="color:var(--accent);word-break:break-all">\1</a>',
        body,
    )
    body = body.replace("\n\n", "</p><p>")
    return f"<p>{body}</p>"


# fallback <details> 안의 raw markdown body 구분자 — editor_notes 의 <div class="notes">
# 와 충돌하지 않도록 style="margin-top:16px" 마커 또는 "구조화 파싱 실패" 카드 컨텍스트로
# 매칭. (구조화 파싱 실패 케이스는 style 없음 → 본문에 카드 title 이 있어 구분 가능)
FALLBACK_NOTES_PAT = re.compile(
    r'(<div class="notes" style="margin-top:16px">)(.*?)(</div>)',
    re.DOTALL,
)
FALLBACK_EMPTY_NOTES_PAT = re.compile(
    r'(📄 원본 요약 \(구조화 파싱 실패\)</h2></div>\s*<div class="card-body"><div class="notes">)(.*?)(</div></div></div>)',
    re.DOTALL,
)

RAW_MARKDOWN_CARD_PAT = re.compile(
    r'(<div class="card"><div class="card-body">.*?원본 요약 마크다운 보기.*?</div></div>)',
    re.DOTALL,
)
NAVER_CARD_PROBE = 'id="naverCafeTemplate"'
NAVER_COPY_FUNC_PROBE = "async function copyNaverCafeHtml"
CHZZK_CARD_PROBE = 'id="chzzkCommentPreview"'
CHZZK_COPY_FUNC_PROBE = "async function copyChzzkCommentText"
CHZZK_CSS_PROBE = ".chzzk-comment-preview {"
NAVER_EXPORT_CSS = """
  .export-help { color: var(--muted); margin-bottom: 14px; }
  .export-actions { display: flex; align-items: center; gap: 12px; margin-bottom: 14px; flex-wrap: wrap; }
  .export-btn {
    appearance: none; border: 1px solid rgba(122,162,247,0.35); cursor: pointer;
    background: rgba(122,162,247,0.12); color: var(--text-strong);
    padding: 10px 14px; border-radius: 10px; font-size: 14px; font-weight: 600;
  }
  .export-btn:hover { background: rgba(122,162,247,0.18); }
  .export-status { color: var(--muted); font-size: 13px; }
  .export-preview summary {
    cursor: pointer; color: var(--muted); font-family: 'JetBrains Mono', 'Cascadia Code', 'Fira Code', Consolas, 'Courier New', monospace;
    font-size: 13px;
  }
  .naver-preview {
    margin-top: 14px; background: var(--surface-2); border: 1px solid var(--border-soft);
    border-radius: 12px; padding: 18px; color: var(--text-strong);
  }
  .naver-preview h2 { font-size: 21px; margin: 0 0 10px; color: var(--text-strong); }
  .naver-preview p { margin: 0 0 10px; }
  .naver-preview blockquote {
    margin: 0; padding: 12px 16px; border-left: 3px solid var(--accent-warm);
    background: rgba(224,175,104,0.08); color: var(--text-strong);
  }
  .naver-preview hr {
    border: 0; border-top: 1px solid var(--border); margin: 18px 0;
  }
  .naver-preview a { color: var(--accent); word-break: break-all; }
  .clipboard-sandbox {
    position: fixed; left: -9999px; top: 0; opacity: 0; pointer-events: none;
  }
""".strip()
CHZZK_EXPORT_CSS = """
  .chzzk-comment-preview {
    margin: 0; background: var(--surface-2); border: 1px solid var(--border-soft);
    border-radius: 12px; padding: 16px 18px; color: var(--text-strong);
    font-family: 'JetBrains Mono', 'Cascadia Code', 'Fira Code', Consolas, 'Courier New', monospace;
    font-size: 13px; line-height: 1.7; white-space: pre-wrap; word-break: break-word;
    max-height: 420px; overflow: auto;
  }
""".strip()
NAVER_COPY_FUNC = """
async function copyNaverCafeHtml(btn) {
  const template = document.getElementById('naverCafeTemplate');
  const status = document.getElementById('naverCafeCopyStatus');
  const sandbox = document.getElementById('naverCafeClipboard');
  if (!template || !status || !sandbox) return;

  const html = template.innerHTML.trim();
  const text = (template.content.textContent || '')
    .replace(/\\u00a0/g, ' ')
    .replace(/\\n\\s*\\n\\s*\\n+/g, '\\n\\n')
    .trim();

  try {
    if (navigator.clipboard && window.ClipboardItem) {
      await navigator.clipboard.write([
        new ClipboardItem({
          'text/html': new Blob([html], { type: 'text/html' }),
          'text/plain': new Blob([text], { type: 'text/plain' })
        })
      ]);
    } else {
      sandbox.innerHTML = html;
      const range = document.createRange();
      range.selectNodeContents(sandbox);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      const ok = document.execCommand('copy');
      selection.removeAllRanges();
      sandbox.innerHTML = '';
      if (!ok) throw new Error('execCommand copy failed');
    }
    status.textContent = '복사됨. 네이버 카페 글쓰기 창에 바로 붙여넣으세요.';
    btn.blur();
  } catch (err) {
    status.textContent = '브라우저가 HTML 복사를 막았습니다. 미리보기 내용을 직접 복사해 주세요.';
  }
}
""".strip()
CHZZK_COPY_FUNC = """
async function copyChzzkCommentText(btn) {
  const pre = document.getElementById('chzzkCommentPreview');
  const status = document.getElementById('chzzkCommentCopyStatus');
  if (!pre || !status) return;
  const text = pre.textContent || '';
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
    } else {
      const range = document.createRange();
      range.selectNodeContents(pre);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      const ok = document.execCommand('copy');
      selection.removeAllRanges();
      if (!ok) throw new Error('execCommand copy failed');
    }
    status.textContent = '복사됨. 치지직 다시보기 댓글창에 바로 붙여넣으세요.';
    btn.blur();
  } catch (err) {
    status.textContent = '브라우저가 복사를 막았습니다. 미리보기 내용을 직접 복사해 주세요.';
  }
}
""".strip()


def _build_chzzk_export_card(md_text: str) -> str:
    sec = _parse_summary_sections(md_text)
    text = _render_chzzk_comment_text(sec)
    if not text:
        return ""
    escaped = _html_escape(text)
    return f'''
<div class="card">
  <div class="card-head"><h2>치지직 다시보기 댓글 붙여넣기용</h2></div>
  <div class="card-body">
    <p class="export-help">버튼을 누르면 아래 타임라인 텍스트가 그대로 복사됩니다. 치지직 다시보기 댓글창에 바로 붙여넣으세요.</p>
    <div class="export-actions">
      <button type="button" class="export-btn" onclick="copyChzzkCommentText(this)">텍스트 복사</button>
      <span class="export-status" id="chzzkCommentCopyStatus" aria-live="polite"></span>
    </div>
    <pre class="chzzk-comment-preview" id="chzzkCommentPreview">{escaped}</pre>
  </div>
</div>'''.strip()


def _build_naver_export_card(vod_info: VODInfo, public_base: str, md_text: str) -> str:
    sec = _parse_summary_sections(md_text)
    naver_cafe_html = _render_naver_cafe_html(vod_info, public_base, sec)
    return f'''
<div class="card">
  <div class="card-head"><h2>네이버 카페 붙여넣기</h2></div>
  <div class="card-body">
    <p class="export-help">버튼을 누르면 네이버 카페 글쓰기 창에 바로 붙여넣기 쉬운 HTML이 복사됩니다.</p>
    <div class="export-actions">
      <button type="button" class="export-btn" onclick="copyNaverCafeHtml(this)">HTML 복사</button>
      <span class="export-status" id="naverCafeCopyStatus" aria-live="polite"></span>
    </div>
    <details class="export-preview">
      <summary>붙여넣기용 미리보기</summary>
      <div class="naver-preview">{naver_cafe_html}</div>
    </details>
    <template id="naverCafeTemplate">{naver_cafe_html}</template>
    <div id="naverCafeClipboard" class="clipboard-sandbox" aria-hidden="true"></div>
  </div>
</div>'''.strip()


def patch_html(html_text: str, meta: dict, public_base: str,
               inline_script: str, md_text: str) -> tuple[str, list[str]]:
    """HTML in-place 패치.

    마이그레이션 내용:
    - chart.js inline 치환
    - OG/Twitter 메타태그 (없으면) 삽입
    - 구 publish-link 배너 div 제거 (구 마이그레이션 잔해)
    - fallback <details> 안의 raw markdown body 를 업데이트된 .md 로 재렌더
      (→ 링크가 제목 아래로 이동 + 하이라이트 multiline 포맷 반영)
    """
    changes: list[str] = []
    report_url = _report_url(meta, public_base)
    vod_info = VODInfo(
        video_no=str(meta.get("video_no") or ""),
        title=meta.get("title") or "",
        channel_id=meta.get("channel_id") or "",
        channel_name=meta.get("channel") or "",
        duration=int(meta.get("duration") or 0),
        publish_date=meta.get("publish_date") or "",
        category=meta.get("category") or "",
        thumbnail_url=meta.get("thumbnail_url") or "",
        streamer_id=meta.get("streamer_id") or "",
    )

    # 1. chart.js inline
    if OLD_SCRIPT_TAG in html_text:
        html_text = html_text.replace(OLD_SCRIPT_TAG, inline_script, 1)
        changes.append("chart-inline")

    # 2. 구 publish-link 배너 div 제거
    new_text, n = OLD_PUBLISH_LINK_PAT.subn("", html_text)
    if n:
        html_text = new_text
        changes.append("remove-old-banner")

    # 2b. 이전 마이그레이션이 editor_notes <div class="notes"> 안에 실수로 주입한
    # 링크 <p> 블록 제거 (원래는 fallback 에만 들어갔어야 하는데 regex 가 첫 번째
    # notes 를 매칭해서 에디터 후기 카드 상단에 붙었었다).
    stray_link_p = re.compile(
        r'<p><strong>🔗 요약 웹페이지:</strong>.*?<strong>▶️ 치지직 다시보기:</strong>.*?</p>',
        re.DOTALL,
    )
    new_text, n = stray_link_p.subn("", html_text)
    if n:
        html_text = new_text
        changes.append("remove-stray-links")

    # 3. OG 메타태그 삽입 (이미 있으면 스킵)
    if OG_PROBE not in html_text:
        og_meta = _build_og_meta(meta, md_text, report_url)
        html_text = re.sub(
            r"(</title>)",
            lambda _m: "</title>\n" + og_meta,
            html_text,
            count=1,
        )
        changes.append("og-meta")

    # 4. fallback body 재렌더 (updated .md 로부터) — 기존 body 와 동일하면 skip
    new_body = _render_fallback_body(md_text)
    for pat in (FALLBACK_NOTES_PAT, FALLBACK_EMPTY_NOTES_PAT):
        m = pat.search(html_text)
        if not m:
            continue
        if m.group(2) == new_body:
            break  # 이미 최신
        html_text = html_text[:m.start()] + m.group(1) + new_body + m.group(3) + html_text[m.end():]
        changes.append("body-rerender")
        break

    naver_card_html = _build_naver_export_card(vod_info, public_base, md_text)
    if NAVER_CARD_PROBE not in html_text:
        m = RAW_MARKDOWN_CARD_PAT.search(html_text)
        if m:
            html_text = html_text[:m.start()] + naver_card_html + "\n\n" + html_text[m.start():]
            changes.append("naver-card")
    if ".export-help {" not in html_text:
        html_text, n = re.subn(r"(</style>)", lambda _m: NAVER_EXPORT_CSS + "\n\n</style>", html_text, count=1)
        if n:
            changes.append("naver-css")
    if NAVER_COPY_FUNC_PROBE not in html_text:
        html_text, n = re.subn(r"(</script>)", lambda _m: NAVER_COPY_FUNC + "\n</script>", html_text, count=1)
        if n:
            changes.append("naver-js")

    chzzk_card_html = _build_chzzk_export_card(md_text)
    if chzzk_card_html and CHZZK_CARD_PROBE not in html_text:
        # 이미 네이버 카페 카드가 있으면 그 바로 뒤에 삽입. 아니면 raw md 카드 앞에.
        naver_end_pat = re.compile(
            r'(<template id="naverCafeTemplate">.*?</template>\s*<div id="naverCafeClipboard"[^>]*></div>\s*</div>\s*</div>)',
            re.DOTALL,
        )
        m = naver_end_pat.search(html_text)
        if m:
            html_text = html_text[:m.end()] + "\n\n" + chzzk_card_html + html_text[m.end():]
            changes.append("chzzk-card")
        else:
            m2 = RAW_MARKDOWN_CARD_PAT.search(html_text)
            if m2:
                html_text = html_text[:m2.start()] + chzzk_card_html + "\n\n" + html_text[m2.start():]
                changes.append("chzzk-card")
    if chzzk_card_html and CHZZK_CSS_PROBE not in html_text:
        html_text, n = re.subn(r"(</style>)", lambda _m: CHZZK_EXPORT_CSS + "\n\n</style>", html_text, count=1)
        if n:
            changes.append("chzzk-css")
    if chzzk_card_html and CHZZK_COPY_FUNC_PROBE not in html_text:
        html_text, n = re.subn(r"(</script>)", lambda _m: CHZZK_COPY_FUNC + "\n</script>", html_text, count=1)
        if n:
            changes.append("chzzk-js")

    return html_text, changes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--output-dir", default=None)
    ap.add_argument(
        "--no-publish", action="store_true",
        help="변경 후 site 재빌드/배포 훅을 건너뛴다 (기본은 config 플래그 따라 실행).",
    )
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

        vod = VODInfo(
            video_no=str(meta.get("video_no") or ""),
            title=meta.get("title") or "",
            channel_id=meta.get("channel_id") or "",
            channel_name=meta.get("channel") or "",
            duration=int(meta.get("duration") or 0),
            publish_date=meta.get("publish_date") or "",
            category=meta.get("category") or "",
            thumbnail_url=meta.get("thumbnail_url") or "",
            streamer_id=meta.get("streamer_id") or "",
        )

        md_path = hp.with_suffix(".md")
        md_changed, md_text_now = _md_migrate(md_path, vod, public_base, args.dry_run)

        try:
            html_text = hp.read_text(encoding="utf-8")
        except OSError as e:
            print(f"  읽기 실패: {hp.name} ({e})")
            continue

        new_html, changes = patch_html(html_text, meta, public_base, inline_script, md_text_now)
        if md_changed:
            changes = ["md-migrate"] + changes

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

    # 변경된 파일이 있으면 site 재빌드 + (선택) Cloudflare 배포를 수행.
    if total_changed > 0 and not args.dry_run and not args.no_publish:
        if cfg.get("publish_autorebuild", False):
            try:
                from publish.hook import rebuild_site_safe, deploy_to_cloudflare_safe
                print("\n[publish] site 재빌드 중...")
                result = rebuild_site_safe(
                    output_dir=out_dir,
                    site_dir=cfg.get("publish_site_dir", "./site"),
                )
                if result is None:
                    print("[publish] 재빌드 실패 또는 스킵")
                else:
                    print(
                        f"[publish] ✓ 재빌드 완료: vods={result['vod_count']}, "
                        f"streamers={result['streamer_count']}"
                    )
                    if cfg.get("publish_autodeploy", False):
                        print("[publish] Cloudflare Pages 배포 중...")
                        ok = deploy_to_cloudflare_safe(
                            site_dir=result["site_dir"],
                            project_name=cfg.get("publish_cloudflare_project", ""),
                        )
                        print(f"[publish] 배포 {'완료' if ok else '실패'}")
            except Exception as e:  # noqa: BLE001
                print(f"[publish] 자동 퍼블리시 중 예외 (무시): {e}")
        else:
            print("\n[publish] publish_autorebuild=false — 스킵")

    return 0


if __name__ == "__main__":
    sys.exit(main())
