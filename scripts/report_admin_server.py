from __future__ import annotations

import argparse
import json
import re
import sys
import threading
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.config import derive_streamer_id, get_public_url_base, load_config  # noqa: E402
from pipeline.models import VODInfo  # noqa: E402
from pipeline.summarizer import (  # noqa: E402
    _build_og_meta,
    _html_escape,
    _parse_summary_sections,
    _postprocess_summary_md,
    _render_inline_md,
    _render_naver_cafe_html,
    _render_chzzk_comment_text,
)
from publish.hook import deploy_to_cloudflare_safe, rebuild_site_safe  # noqa: E402


LIST_PAGE = """<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Report Admin</title>
  <style>
    :root {
      --bg: #0f1420;
      --panel: #171d2c;
      --panel-2: #20283b;
      --border: #2d3750;
      --text: #eef3ff;
      --muted: #98a4c2;
      --accent: #6dd3a0;
      --danger: #ff8e8e;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Segoe UI", "Malgun Gothic", sans-serif;
      background: radial-gradient(circle at top, rgba(109,211,160,0.08), transparent 30%), var(--bg);
      color: var(--text);
    }
    .page {
      max-width: 1180px;
      margin: 0 auto;
      padding: 32px 24px 48px;
    }
    h1 {
      margin: 0;
      font-size: 30px;
    }
    .sub {
      margin-top: 10px;
      color: var(--muted);
      line-height: 1.7;
      font-size: 14px;
    }
    .toolbar {
      margin-top: 24px;
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 12px;
      align-items: center;
    }
    input[type="text"] {
      width: 100%;
      padding: 12px 14px;
      border-radius: 12px;
      border: 1px solid var(--border);
      background: var(--panel);
      color: var(--text);
      font: inherit;
    }
    button {
      padding: 12px 16px;
      border-radius: 12px;
      border: 1px solid var(--border);
      background: var(--panel);
      color: var(--text);
      font: inherit;
      cursor: pointer;
    }
    button:hover { filter: brightness(1.08); }
    .meta {
      margin-top: 12px;
      color: var(--muted);
      font-size: 13px;
    }
    .streamer-bar {
      margin-top: 18px;
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    .chip {
      padding: 6px 12px;
      border-radius: 999px;
      border: 1px solid var(--border);
      background: var(--panel);
      color: var(--muted);
      font-size: 13px;
      cursor: pointer;
    }
    .chip.active {
      color: var(--text);
      border-color: rgba(109,211,160,0.55);
      background: rgba(109,211,160,0.12);
    }
    .chip .count {
      margin-left: 6px;
      opacity: 0.7;
      font-size: 11px;
    }
    .group {
      margin-top: 22px;
    }
    .group-head {
      margin: 0 0 10px;
      font-size: 15px;
      color: var(--muted);
      display: flex;
      align-items: baseline;
      gap: 10px;
    }
    .group-head .group-count {
      font-size: 12px;
      opacity: 0.7;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
      gap: 14px;
    }
    .card {
      display: block;
      text-decoration: none;
      color: inherit;
      background: rgba(23, 29, 44, 0.92);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 16px;
    }
    .card:hover {
      border-color: rgba(109,211,160,0.4);
      transform: translateY(-1px);
    }
    .title {
      font-size: 15px;
      line-height: 1.5;
      word-break: break-word;
    }
    .row {
      margin-top: 10px;
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      color: var(--muted);
      font-size: 12px;
    }
    .badge {
      display: inline-block;
      padding: 3px 8px;
      border-radius: 999px;
      border: 1px solid var(--border);
      color: var(--muted);
      font-size: 11px;
    }
    .empty {
      margin-top: 22px;
      padding: 18px;
      border-radius: 14px;
      border: 1px solid var(--border);
      background: var(--panel);
      color: var(--muted);
    }
    .error {
      color: var(--danger);
      margin-top: 14px;
      font-size: 13px;
    }
    @media (max-width: 760px) {
      .toolbar { grid-template-columns: 1fr; }
      .page { padding: 24px 16px 36px; }
      .grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <main class="page">
    <h1>관리자 리포트 목록</h1>
    <div class="sub">
      로컬 전용 관리자 화면입니다. 여기서는 전체 리포트를 검색하고 선택만 하고,
      실제 편집은 별도 편집 페이지에서 진행합니다.
    </div>
    <div class="toolbar">
      <input id="search" type="text" placeholder="제목 또는 영상 번호 검색">
      <button id="reloadBtn" type="button">목록 새로고침</button>
    </div>
    <div id="meta" class="meta">불러오는 중...</div>
    <div id="error" class="error"></div>
    <div id="streamerBar" class="streamer-bar"></div>
    <div id="list"></div>
  </main>
  <script>
    const searchEl = document.getElementById('search');
    const listEl = document.getElementById('list');
    const metaEl = document.getElementById('meta');
    const errorEl = document.getElementById('error');
    const streamerBarEl = document.getElementById('streamerBar');
    let reports = [];
    let activeStreamer = '__all__';

    async function api(path) {
      const res = await fetch(path);
      const text = await res.text();
      let data = {};
      try { data = text ? JSON.parse(text) : {}; } catch { data = { raw: text }; }
      if (!res.ok) throw new Error(data.error || data.raw || `HTTP ${res.status}`);
      return data;
    }

    function streamerKey(report) {
      return report.streamer_id || report.channel_id || report.channel || '__unknown__';
    }
    function streamerLabel(report) {
      return report.channel || report.streamer_id || '(unknown)';
    }
    function escapeHtml(s) {
      return String(s || '').replace(/[&<>"']/g, (c) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
      }[c]));
    }
    function label(report) {
      return `${report.video_no} ${report.title} ${streamerLabel(report)} ${report.site_only ? 'site-only' : ''}`.toLowerCase();
    }

    function renderStreamerBar() {
      const counts = new Map();
      const names = new Map();
      reports.forEach((r) => {
        const key = streamerKey(r);
        counts.set(key, (counts.get(key) || 0) + 1);
        if (!names.has(key)) names.set(key, streamerLabel(r));
      });
      const entries = Array.from(counts.entries()).sort((a, b) => b[1] - a[1]);
      const parts = [`<button class="chip${activeStreamer === '__all__' ? ' active' : ''}" data-key="__all__">전체<span class="count">${reports.length}</span></button>`];
      entries.forEach(([key, count]) => {
        const name = names.get(key) || key;
        parts.push(`<button class="chip${activeStreamer === key ? ' active' : ''}" data-key="${escapeHtml(key)}">${escapeHtml(name)}<span class="count">${count}</span></button>`);
      });
      streamerBarEl.innerHTML = parts.join('');
      streamerBarEl.querySelectorAll('.chip').forEach((btn) => {
        btn.addEventListener('click', () => {
          activeStreamer = btn.dataset.key;
          render();
        });
      });
    }

    function renderCard(report) {
      const anchor = document.createElement('a');
      anchor.className = 'card';
      anchor.href = `/report?base=${encodeURIComponent(report.base)}`;
      anchor.innerHTML = `
        <div class="title">${escapeHtml(report.title)}</div>
        <div class="row">
          <span>${escapeHtml(report.video_no)}</span>
          <span class="badge">${escapeHtml(streamerLabel(report))}</span>
          ${report.publish_date ? `<span>${escapeHtml(report.publish_date)}</span>` : ''}
          ${report.site_only ? '<span class="badge">site-only</span>' : ''}
        </div>
      `;
      return anchor;
    }

    function render() {
      const keyword = (searchEl.value || '').trim().toLowerCase();
      const filtered = reports.filter((report) => {
        if (activeStreamer !== '__all__' && streamerKey(report) !== activeStreamer) return false;
        if (keyword && !label(report).includes(keyword)) return false;
        return true;
      });
      metaEl.textContent = `전체 ${reports.length}개 · 현재 ${filtered.length}개`;
      renderStreamerBar();
      listEl.innerHTML = '';
      if (!filtered.length) {
        listEl.innerHTML = '<div class="empty">검색 결과가 없습니다.</div>';
        return;
      }

      if (activeStreamer === '__all__') {
        const groups = new Map();
        filtered.forEach((r) => {
          const key = streamerKey(r);
          if (!groups.has(key)) groups.set(key, { name: streamerLabel(r), items: [] });
          groups.get(key).items.push(r);
        });
        const sorted = Array.from(groups.entries()).sort((a, b) => b[1].items.length - a[1].items.length);
        sorted.forEach(([_, group]) => {
          const section = document.createElement('section');
          section.className = 'group';
          const head = document.createElement('h2');
          head.className = 'group-head';
          head.innerHTML = `${escapeHtml(group.name)} <span class="group-count">${group.items.length}개</span>`;
          const grid = document.createElement('div');
          grid.className = 'grid';
          group.items.forEach((r) => grid.appendChild(renderCard(r)));
          section.appendChild(head);
          section.appendChild(grid);
          listEl.appendChild(section);
        });
      } else {
        const grid = document.createElement('div');
        grid.className = 'grid';
        filtered.forEach((r) => grid.appendChild(renderCard(r)));
        listEl.appendChild(grid);
      }
    }

    async function loadReports() {
      errorEl.textContent = '';
      const data = await api('/api/reports');
      reports = data.reports || [];
      render();
    }

    searchEl.addEventListener('input', render);
    document.getElementById('reloadBtn').addEventListener('click', () => {
      loadReports().catch((err) => { errorEl.textContent = err.message; });
    });

    loadReports().catch((err) => {
      metaEl.textContent = '불러오기 실패';
      errorEl.textContent = err.message;
    });
  </script>
</body>
</html>
"""


EDIT_PAGE = """<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Report Editor</title>
  <style>
    :root {
      --bg: #10141f;
      --panel: #171d2c;
      --panel-2: #20283b;
      --border: #2d3750;
      --text: #eef3ff;
      --muted: #98a4c2;
      --accent: #6dd3a0;
      --warn: #ffcf6e;
      --danger: #ff8e8e;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Segoe UI", "Malgun Gothic", sans-serif;
      background: var(--bg);
      color: var(--text);
    }
    .app {
      display: grid;
      grid-template-columns: minmax(460px, 680px) 1fr;
      min-height: 100vh;
    }
    .sidebar {
      border-right: 1px solid var(--border);
      background: var(--panel);
      padding: 18px;
      overflow: auto;
    }
    .main {
      display: flex;
      flex-direction: column;
      min-width: 0;
    }
    h1 {
      margin: 0 0 10px;
      font-size: 24px;
      line-height: 1.45;
    }
    .muted {
      color: var(--muted);
      font-size: 13px;
      line-height: 1.6;
    }
    textarea, button, input[type="checkbox"] {
      font: inherit;
    }
    textarea {
      width: 100%;
      min-height: 56vh;
      padding: 12px;
      resize: vertical;
      line-height: 1.6;
      white-space: pre;
      background: var(--panel-2);
      color: var(--text);
      border: 1px solid var(--border);
      border-radius: 10px;
    }
    .topbar {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      align-items: center;
      margin-bottom: 12px;
    }
    .topbar a {
      color: var(--accent);
      text-decoration: none;
      font-size: 13px;
    }
    .row {
      display: flex;
      gap: 10px;
      align-items: center;
      flex-wrap: wrap;
      margin-top: 12px;
    }
    button {
      border: 1px solid var(--border);
      background: var(--panel-2);
      color: var(--text);
      padding: 10px 14px;
      border-radius: 10px;
      cursor: pointer;
    }
    button.primary {
      background: rgba(109, 211, 160, 0.14);
      border-color: rgba(109, 211, 160, 0.35);
    }
    button:hover { filter: brightness(1.08); }
    .checkbox {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      color: var(--muted);
      font-size: 13px;
    }
    .status {
      margin-top: 12px;
      min-height: 20px;
      color: var(--warn);
      font-size: 13px;
    }
    .preview-bar {
      padding: 14px 18px;
      border-bottom: 1px solid var(--border);
      background: var(--panel);
      display: flex;
      gap: 12px;
      align-items: center;
      justify-content: space-between;
    }
    .preview-title {
      font-size: 14px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    iframe {
      flex: 1;
      width: 100%;
      border: 0;
      background: white;
    }
    @media (max-width: 1100px) {
      .app { grid-template-columns: 1fr; }
      .sidebar { border-right: 0; border-bottom: 1px solid var(--border); }
      textarea { min-height: 40vh; }
    }
  </style>
</head>
<body>
  <div class="app">
    <aside class="sidebar">
      <div class="topbar">
        <a href="/">← 목록으로</a>
        <a id="publicLink" href="#" target="_blank" rel="noopener">공개 리포트 열기</a>
      </div>
      <h1 id="title">리포트 불러오는 중...</h1>
      <div id="meta" class="muted"></div>
      <label class="muted" for="mdEditor" style="display:block;margin-top:16px;">원본 요약 마크다운</label>
      <textarea id="mdEditor" spellcheck="false"></textarea>
      <div class="row">
        <button id="previewBtn" type="button">미리보기 갱신</button>
        <button id="saveBtn" class="primary" type="button">저장</button>
        <button id="reloadBtn" type="button">원본 다시 불러오기</button>
        <label class="checkbox"><input id="publishCheckbox" type="checkbox" checked> 저장 후 반영</label>
      </div>
      <div id="status" class="status"></div>
    </aside>
    <main class="main">
      <div class="preview-bar">
        <div>
          <div id="previewTitle" class="preview-title">미리보기</div>
          <div id="previewInfo" class="muted"></div>
        </div>
      </div>
      <iframe id="previewFrame" title="preview"></iframe>
    </main>
  </div>
  <script>
    const params = new URLSearchParams(location.search);
    const base = params.get('base') || '';
    const titleEl = document.getElementById('title');
    const metaEl = document.getElementById('meta');
    const publicLinkEl = document.getElementById('publicLink');
    const mdEditor = document.getElementById('mdEditor');
    const previewTitleEl = document.getElementById('previewTitle');
    const previewInfoEl = document.getElementById('previewInfo');
    const previewFrame = document.getElementById('previewFrame');
    const publishCheckbox = document.getElementById('publishCheckbox');
    const statusEl = document.getElementById('status');

    function setStatus(msg, isError = false) {
      statusEl.textContent = msg || '';
      statusEl.style.color = isError ? 'var(--danger)' : 'var(--warn)';
    }

    async function api(path, options = {}) {
      const res = await fetch(path, {
        headers: { 'Content-Type': 'application/json' },
        ...options,
      });
      const text = await res.text();
      let data = {};
      try { data = text ? JSON.parse(text) : {}; } catch { data = { raw: text }; }
      if (!res.ok) throw new Error(data.error || data.raw || `HTTP ${res.status}`);
      return data;
    }

    async function loadReport() {
      if (!base) throw new Error('base 파라미터가 없습니다.');
      const data = await api(`/api/report?base=${encodeURIComponent(base)}`);
      titleEl.textContent = data.title;
      metaEl.textContent = `${data.video_no} · ${data.channel}${data.site_only ? ' · site-only' : ''}`;
      mdEditor.value = data.md;
      publicLinkEl.href = data.public_report_url || '#';
      publicLinkEl.style.visibility = data.public_report_url ? 'visible' : 'hidden';
      previewTitleEl.textContent = data.title;
      previewInfoEl.textContent = `${data.video_no} · ${data.channel}`;
      await previewCurrent();
    }

    async function previewCurrent() {
      if (!base) return;
      setStatus('미리보기 생성 중...');
      const data = await api('/api/preview', {
        method: 'POST',
        body: JSON.stringify({ base, md: mdEditor.value }),
      });
      previewFrame.srcdoc = data.html;
      previewTitleEl.textContent = data.title || titleEl.textContent;
      setStatus('미리보기 갱신 완료');
    }

    async function saveCurrent() {
      if (!base) return;
      setStatus('저장 중...');
      const data = await api('/api/save', {
        method: 'POST',
        body: JSON.stringify({
          base,
          md: mdEditor.value,
          publish: publishCheckbox.checked,
        }),
      });
      previewFrame.srcdoc = data.html;
      previewTitleEl.textContent = data.title || titleEl.textContent;
      setStatus(data.message || '저장 완료');
    }

    document.getElementById('reloadBtn').addEventListener('click', () => {
      loadReport().catch((err) => setStatus(err.message, true));
    });
    document.getElementById('previewBtn').addEventListener('click', () => {
      previewCurrent().catch((err) => setStatus(err.message, true));
    });
    document.getElementById('saveBtn').addEventListener('click', () => {
      saveCurrent().catch((err) => setStatus(err.message, true));
    });

    loadReport().catch((err) => {
      titleEl.textContent = '리포트를 불러올 수 없습니다.';
      setStatus(err.message, true);
    });
  </script>
</body>
</html>
"""


HEADER_H1_RE = re.compile(r"(<header\b.*?<h1[^>]*>)(.*?)(</h1>)", re.DOTALL)
HEADER_INSERT_RE = re.compile(
    r"(</header>\s*)(?:<div class=\"hero\">.*?</div>\s*)?(?=<div class=\"stats-wrap\"|<div class=\"stats\")",
    re.DOTALL,
)
TITLE_TAG_RE = re.compile(r"<title>.*?</title>", re.DOTALL)
OG_META_RE = re.compile(
    r'(<meta property="og:type" content="article">.*?<meta name="twitter:description" content=".*?">)',
    re.DOTALL,
)
CHART_CARD_RE = re.compile(
    r"<div class=\"card\">.*?<canvas id=\"chatChart\"></canvas>.*?</div>",
    re.DOTALL,
)
BOTTOM_SCRIPT_RE = re.compile(r"<script>\s*const labels =", re.DOTALL)


@dataclass
class ReportPaths:
    base: str
    video_no: str
    md_path: Path | None
    html_path: Path | None
    meta_path: Path | None
    site_md_path: Path | None
    site_html_path: Path | None
    site_meta_path: Path | None
    site_only: bool


def _make_base_from_meta(video_no: str, meta: dict) -> str:
    publish_date = str(meta.get("publish_date") or "")
    day = publish_date.split(" ")[0].replace("-", "")
    title = str(meta.get("title") or "").strip()
    if day and title:
        return f"{video_no}_{day}_{title}"
    if title:
        return f"{video_no}_{title}"
    return video_no


def _find_reports(output_dir: Path, site_dir: Path) -> list[ReportPaths]:
    reports_by_video: dict[str, ReportPaths] = {}

    for meta_path in sorted(output_dir.glob("*_metadata.json")):
        base = meta_path.name[: -len("_metadata.json")]
        md_path = output_dir / f"{base}.md"
        html_path = output_dir / f"{base}.html"
        if not (md_path.exists() and html_path.exists()):
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        video_no = str(meta.get("video_no") or base.split("_", 1)[0])
        reports_by_video[video_no] = ReportPaths(
            base=base,
            video_no=video_no,
            md_path=md_path,
            html_path=html_path,
            meta_path=meta_path,
            site_md_path=site_dir / "vods" / video_no / "report.md",
            site_html_path=site_dir / "vods" / video_no / "report.html",
            site_meta_path=site_dir / "vods" / video_no / "metadata.json",
            site_only=False,
        )

    vods_dir = site_dir / "vods"
    if vods_dir.exists():
        for vod_dir in sorted(path for path in vods_dir.iterdir() if path.is_dir()):
            video_no = vod_dir.name
            if video_no in reports_by_video:
                continue
            site_meta_path = vod_dir / "metadata.json"
            site_md_path = vod_dir / "report.md"
            site_html_path = vod_dir / "report.html"
            if not (site_meta_path.exists() and site_md_path.exists() and site_html_path.exists()):
                continue
            meta = json.loads(site_meta_path.read_text(encoding="utf-8"))
            reports_by_video[video_no] = ReportPaths(
                base=_make_base_from_meta(video_no, meta),
                video_no=video_no,
                md_path=None,
                html_path=None,
                meta_path=None,
                site_md_path=site_md_path,
                site_html_path=site_html_path,
                site_meta_path=site_meta_path,
                site_only=True,
            )

    return sorted(reports_by_video.values(), key=lambda item: (item.video_no, item.base))


def _load_report_context(paths: ReportPaths, cfg: dict) -> dict:
    meta_path = paths.meta_path or paths.site_meta_path
    html_path = paths.html_path or paths.site_html_path
    md_path = paths.md_path or paths.site_md_path
    if meta_path is None or html_path is None or md_path is None:
        raise FileNotFoundError(f"report files missing: {paths.base}")

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    public_base = get_public_url_base(cfg)
    vod_info = VODInfo(
        video_no=str(meta.get("video_no") or paths.video_no),
        title=meta.get("title") or "",
        channel_id=meta.get("channel_id") or "",
        channel_name=meta.get("channel") or "",
        duration=int(meta.get("duration") or 0),
        publish_date=meta.get("publish_date") or "",
        thumbnail_url=meta.get("thumbnail_url") or "",
        category=meta.get("category") or "",
        streamer_id=meta.get("streamer_id") or "",
    )
    return {
        "meta": meta,
        "md": md_path.read_text(encoding="utf-8"),
        "html": html_path.read_text(encoding="utf-8"),
        "public_base": public_base,
        "vod_info": vod_info,
        "site_only": paths.site_only,
    }


def _render_blocks(summary_md: str, vod_info: VODInfo, public_url_base: str) -> dict:
    sec = _parse_summary_sections(summary_md)
    title_display = sec["title"] or vod_info.title

    tag_chips = ""
    if sec["hashtags"]:
        tag_chips = "\n".join(f'<span class="tag">#{_html_escape(tag)}</span>' for tag in sec["hashtags"][:6])

    pull_quote_html = ""
    if sec["pull_quote"]:
        pull_quote_html = f'<div class="quote">"{_html_escape(sec["pull_quote"])}"</div>'

    hero_html = ""
    if tag_chips or pull_quote_html:
        hero_html = f"""
<div class="hero"><div class="bleed-inner">
  {f'<div class="tags">{tag_chips}</div>' if tag_chips else ''}
  {pull_quote_html}
</div></div>""".strip()

    timeline_html = ""
    if sec["timeline"]:
        items: list[str] = []
        for item in sec["timeline"]:
            mood_class = f"mood-{item['mood']}"
            mood_emoji = item["mood_raw"] or {"hot": "🔥", "veryhot": "🔥🔥", "chat": "💬", "chill": "🫠"}.get(item["mood"], "")
            evidence_html = (
                f'<div class="t-evidence">{_render_inline_md(item["evidence"])}</div>'
                if item["evidence"]
                else ""
            )
            items.append(
                f"""
<div class="t-item {mood_class}">
  <div class="t-head">
    <span class="tc">{item["tc"]}</span>
    <span class="t-title">{_render_inline_md(item["title"])}</span>
    <span class="mood">{_html_escape(mood_emoji)}</span>
  </div>
  <div class="t-body">{_render_inline_md(item["summary"])}</div>
  {evidence_html}
</div>""".strip()
            )
        timeline_html = f"""
<div class="card">
  <div class="card-head">
    <h2>📍 타임라인 상세 요약</h2>
    <button class="t-toggle" onclick="toggleAll(this)">근거 모두 펼치기</button>
  </div>
  <div class="card-body">
    <div class="timeline">{''.join(items)}</div>
  </div>
</div>""".strip()

    highlights_html = ""
    if sec["highlights"]:
        items = []
        for item in sec["highlights"]:
            reason_html = f'<div class="hl-reason">{_render_inline_md(item["reason"])}</div>' if item["reason"] else ""
            items.append(
                f"""
<div class="hl">
  <div class="hl-body">
    <div class="hl-title"><span class="tc">{_html_escape(item["tc_range"])}</span>&nbsp;&nbsp;{_render_inline_md(item["title"])}</div>
    {reason_html}
  </div>
</div>""".strip()
            )
        highlights_html = f"""
<div class="card">
  <div class="card-head"><h2>🎬 하이라이트 추천 구간</h2></div>
  <div class="card-body"><div class="hl-list">{''.join(items)}</div></div>
</div>""".strip()

    notes_html = ""
    if sec["editor_notes"]:
        paragraphs = "\n".join(f"<p>{_render_inline_md(paragraph)}</p>" for paragraph in sec["editor_notes"])
        notes_html = f"""
<div class="card">
  <div class="card-head"><h2>📝 에디터의 방송 후기</h2></div>
  <div class="card-body"><div class="notes">{paragraphs}</div></div>
</div>""".strip()

    naver_cafe_html = _render_naver_cafe_html(vod_info, public_url_base, sec)
    naver_export_html = f"""
<div class="card">
  <div class="card-head"><h2>네이버 카페 붙여넣기</h2></div>
  <div class="card-body">
    <p class="export-help">버튼을 누르면 네이버 카페 글쓰기 창에 바로 붙여넣기 가능한 HTML을 복사합니다.</p>
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
</div>""".strip()

    chzzk_comment_text = _render_chzzk_comment_text(sec)
    chzzk_export_html = ""
    if chzzk_comment_text:
        chzzk_escaped = _html_escape(chzzk_comment_text)
        chzzk_export_html = f"""
<div class="card">
  <div class="card-head"><h2>치지직 다시보기 댓글 붙여넣기용</h2></div>
  <div class="card-body">
    <p class="export-help">버튼을 누르면 아래 타임라인 텍스트가 그대로 복사됩니다. 치지직 다시보기 댓글창에 바로 붙여넣으세요.</p>
    <div class="export-actions">
      <button type="button" class="export-btn" onclick="copyChzzkCommentText(this)">텍스트 복사</button>
      <span class="export-status" id="chzzkCommentCopyStatus" aria-live="polite"></span>
    </div>
    <pre class="chzzk-comment-preview" id="chzzkCommentPreview">{chzzk_escaped}</pre>
  </div>
</div>""".strip()

    escaped = _html_escape(summary_md)
    escaped = re.sub(r"^###\s+(.+)$", r"<h3>\1</h3>", escaped, flags=re.M)
    escaped = re.sub(r"^##\s+(.+)$", r"<h2>\1</h2>", escaped, flags=re.M)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(
        r'\[([^\]]+)\]\((https?://[^)\s]+)\)',
        r'<a href="\2" target="_blank" rel="noopener" style="color:var(--accent);word-break:break-all">\1</a>',
        escaped,
    )
    escaped = escaped.replace("\n\n", "</p><p>")
    fallback_html = (
        '<div class="card"><div class="card-body">'
        '<details><summary style="cursor:pointer;color:var(--muted);font-family:monospace;font-size:13px">'
        '📝 원본 요약 마크다운 보기</summary>'
        f'<div class="notes" style="margin-top:16px"><p>{escaped}</p></div></details></div></div>'
    )

    return {
        "sec": sec,
        "title_display": title_display,
        "hero_html": hero_html,
        "timeline_html": timeline_html,
        "highlights_html": highlights_html,
        "notes_html": notes_html,
        "naver_export_html": naver_export_html,
        "chzzk_export_html": chzzk_export_html,
        "fallback_html": fallback_html,
        "og_meta": _build_og_meta(vod_info, summary_md, public_url_base, sec),
    }


def _replace_title_tag(html: str, title_display: str) -> str:
    new_title = f"<title>{_html_escape(title_display)} | 방송 분석 리포트</title>"
    if TITLE_TAG_RE.search(html):
        return TITLE_TAG_RE.sub(new_title, html, count=1)
    return html


def _patch_report_html(current_html: str, summary_md: str, vod_info: VODInfo, public_url_base: str) -> tuple[str, str]:
    rendered = _render_blocks(summary_md, vod_info, public_url_base)
    html = current_html

    if HEADER_H1_RE.search(html):
        html = HEADER_H1_RE.sub(
            lambda match: f"{match.group(1)}{_html_escape(rendered['title_display'])}{match.group(3)}",
            html,
            count=1,
        )

    if HEADER_INSERT_RE.search(html):
        hero_segment = f"\n{rendered['hero_html']}\n" if rendered["hero_html"] else "\n"
        html = HEADER_INSERT_RE.sub(lambda match: f"{match.group(1)}{hero_segment}", html, count=1)

    chart_match = CHART_CARD_RE.search(html)
    script_match = None
    for match in BOTTOM_SCRIPT_RE.finditer(html):
        script_match = match

    if chart_match and script_match and chart_match.end() < script_match.start():
        body_cards = "\n\n".join(
            block
            for block in [
                rendered["timeline_html"],
                rendered["highlights_html"],
                rendered["notes_html"],
                rendered["naver_export_html"],
                rendered["chzzk_export_html"],
                rendered["fallback_html"],
            ]
            if block
        )
        html = html[: chart_match.end()] + ("\n\n" + body_cards + "\n\n") + html[script_match.start() :]

    html = _replace_title_tag(html, rendered["title_display"])
    if OG_META_RE.search(html):
        html = OG_META_RE.sub(rendered["og_meta"], html, count=1)
    return html, rendered["title_display"]


def _safe_backup(path: Path | None) -> None:
    if path is None or not path.exists():
        return
    backup = path.with_suffix(path.suffix + ".admin.bak")
    if not backup.exists():
        backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")


class ReportAdminApp:
    def __init__(self, output_dir: Path, site_dir: Path, cfg: dict):
        self.output_dir = output_dir
        self.site_dir = site_dir
        self.cfg = cfg
        self.lock = threading.Lock()

    def list_reports(self) -> list[dict]:
        rows = []
        for paths in _find_reports(self.output_dir, self.site_dir):
            meta_path = paths.meta_path or paths.site_meta_path
            if meta_path is None or not meta_path.exists():
                continue
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            channel_id = meta.get("channel_id") or ""
            channel = meta.get("channel") or ""
            # 구 리포트는 streamer_id 가 비어 있거나 snake_case 가 일관되지 않으므로,
            # channel_id → derive_streamer_id 로 강제 정규화해 그룹 키를 일치시킨다.
            streamer_id = meta.get("streamer_id") or derive_streamer_id(channel_id, channel)
            rows.append(
                {
                    "base": paths.base,
                    "video_no": str(meta.get("video_no") or paths.video_no),
                    "title": meta.get("title") or paths.base,
                    "channel": channel,
                    "channel_id": channel_id,
                    "streamer_id": streamer_id,
                    "publish_date": meta.get("publish_date") or "",
                    "site_only": paths.site_only,
                }
            )

        # 2차 병합: channel_id 가 빠진 레거시 레코드를, 같은 channel 이름을
        # 갖고 있으면서 channel_id 가 채워진 다른 레코드의 streamer_id 로 흡수.
        name_to_sid: dict[str, str] = {}
        for row in rows:
            if row["channel_id"] and row["channel"]:
                name_to_sid.setdefault(row["channel"], row["streamer_id"])
        for row in rows:
            if not row["channel_id"] and row["channel"] in name_to_sid:
                row["streamer_id"] = name_to_sid[row["channel"]]
        return rows

    def get_report(self, base: str) -> dict:
        paths = self._paths_for_base(base)
        ctx = _load_report_context(paths, self.cfg)
        public_url = (
            f"{ctx['public_base'].rstrip('/')}/vods/{ctx['vod_info'].video_no}/report"
            if ctx["public_base"]
            else ""
        )
        return {
            "base": base,
            "video_no": ctx["vod_info"].video_no,
            "title": ctx["vod_info"].title,
            "channel": ctx["vod_info"].channel_name,
            "md": ctx["md"],
            "public_report_url": public_url,
            "site_only": ctx["site_only"],
        }

    def preview_report(self, base: str, md_text: str) -> dict:
        paths = self._paths_for_base(base)
        ctx = _load_report_context(paths, self.cfg)
        html, title = _patch_report_html(ctx["html"], md_text, ctx["vod_info"], ctx["public_base"])
        return {"html": html, "title": title}

    def save_report(self, base: str, md_text: str, publish: bool) -> dict:
        paths = self._paths_for_base(base)
        with self.lock:
            ctx = _load_report_context(paths, self.cfg)
            normalized_md = _postprocess_summary_md(md_text, ctx["vod_info"], ctx["public_base"])
            patched_html, title = _patch_report_html(
                ctx["html"],
                normalized_md,
                ctx["vod_info"],
                ctx["public_base"],
            )

            for path in (paths.md_path, paths.html_path, paths.site_md_path, paths.site_html_path):
                _safe_backup(path)

            if paths.md_path is not None:
                paths.md_path.write_text(normalized_md, encoding="utf-8")
            if paths.html_path is not None:
                paths.html_path.write_text(patched_html, encoding="utf-8")
            if paths.site_md_path is not None:
                paths.site_md_path.write_text(normalized_md, encoding="utf-8")
            if paths.site_html_path is not None:
                paths.site_html_path.write_text(patched_html, encoding="utf-8")

            message = "저장만 완료"
            if publish:
                if paths.md_path is not None and paths.html_path is not None:
                    result = rebuild_site_safe(output_dir=self.output_dir, site_dir=self.site_dir)
                    if result is not None:
                        message = f"site 재빌드 완료: vods={result['vod_count']}, streamers={result['streamer_count']}"
                        if self.cfg.get("publish_autodeploy", False):
                            ok = deploy_to_cloudflare_safe(
                                site_dir=result["site_dir"],
                                project_name=self.cfg.get("publish_cloudflare_project", ""),
                            )
                            message += f", Cloudflare 배포 {'완료' if ok else '실패'}"
                    else:
                        message = "site 재빌드 실패"
                else:
                    message = "site-only 리포트 반영 완료"
                    if self.cfg.get("publish_autodeploy", False):
                        ok = deploy_to_cloudflare_safe(
                            site_dir=self.site_dir,
                            project_name=self.cfg.get("publish_cloudflare_project", ""),
                        )
                        message += f", Cloudflare 배포 {'완료' if ok else '실패'}"

        return {"html": patched_html, "title": title, "message": message}

    def _paths_for_base(self, base: str) -> ReportPaths:
        for paths in _find_reports(self.output_dir, self.site_dir):
            if paths.base == base:
                return paths
        raise FileNotFoundError(f"report not found: {base}")


def make_handler(app: ReportAdminApp):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._send_html(LIST_PAGE)
                return
            if parsed.path == "/report":
                self._send_html(EDIT_PAGE)
                return
            if parsed.path == "/api/reports":
                self._send_json({"reports": app.list_reports()})
                return
            if parsed.path == "/api/report":
                qs = parse_qs(parsed.query)
                base = (qs.get("base") or [""])[0]
                try:
                    self._send_json(app.get_report(base))
                except Exception as exc:  # noqa: BLE001
                    self._send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self._send_error_json(HTTPStatus.NOT_FOUND, "not found")

        def do_POST(self):
            parsed = urlparse(self.path)
            try:
                raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                payload = json.loads(raw.decode("utf-8") or "{}")
            except Exception as exc:  # noqa: BLE001
                self._send_error_json(HTTPStatus.BAD_REQUEST, f"invalid json: {exc}")
                return

            try:
                if parsed.path == "/api/preview":
                    self._send_json(app.preview_report(payload.get("base", ""), payload.get("md", "")))
                    return
                if parsed.path == "/api/save":
                    self._send_json(
                        app.save_report(
                            payload.get("base", ""),
                            payload.get("md", ""),
                            bool(payload.get("publish", True)),
                        )
                    )
                    return
                self._send_error_json(HTTPStatus.NOT_FOUND, "not found")
            except Exception as exc:  # noqa: BLE001
                self._send_error_json(HTTPStatus.BAD_REQUEST, str(exc))

        def log_message(self, fmt: str, *args):
            return

        def _send_html(self, body: str):
            data = body.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_json(self, obj: dict, status: HTTPStatus = HTTPStatus.OK):
            data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_error_json(self, status: HTTPStatus, message: str):
            self._send_json({"error": message}, status=status)

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--site-dir", default=None)
    args = parser.parse_args()

    cfg = load_config()
    output_dir = Path(args.output_dir or cfg.get("output_dir", "./output")).resolve()
    site_dir = Path(args.site_dir or cfg.get("publish_site_dir", "./site")).resolve()
    app = ReportAdminApp(output_dir=output_dir, site_dir=site_dir, cfg=cfg)

    server = ThreadingHTTPServer((args.host, args.port), make_handler(app))
    print(f"Report admin server listening on http://{args.host}:{args.port}/")
    print("This server is localhost-only by default and is not meant to be deployed.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
