"""정적 사이트 빌더.

output/ 의 기존 VOD 리포트(md/html/metadata JSON) 를 읽어
site/ 아래의 정적 호스팅 가능한 구조로 변환한다.

사용법:
    python -m publish.builder.build_site
    python -m publish.builder.build_site --output-dir ./output --site-dir ./site

이 빌더는 runtime 파이프라인을 변경하지 않고, publish-view 만 derive 한다.
권위 문서: docs/publish-schema.md, docs/multi-streamer-web-publish-backlog.md.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

KST = timezone(timedelta(hours=9))

# ── 데이터 모델 ───────────────────────────────────────────────

@dataclass
class StreamerRef:
    streamer_id: str
    streamer_name: str
    channel_id: Optional[str]
    platform: str = "chzzk"
    vod_count: int = 0


@dataclass
class VodRecord:
    streamer_id: str
    streamer_name: str
    channel_id: Optional[str]
    platform: str
    video_no: str
    title: str
    published_at: str
    published_date_str: str
    duration_sec: int
    platform_category: Optional[str]
    content_judgement: Optional[str]
    summary_md_path: str
    summary_html_path: str
    metadata_json_path: str
    thumbnail_url: Optional[str]
    search_text: str
    stats: dict
    processed_at: str

    def to_public_dict(self) -> dict:
        return asdict(self)


# ── 유틸 ──────────────────────────────────────────────────────

_VIDEO_FNAME_RE = re.compile(r"^(?P<video_no>\d+)_(?P<date>\d{8})_(?P<rest>.+)$")


def _slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[\s/]+", "-", value)
    value = re.sub(r"[^a-z0-9\-_]", "", value)
    return value or "unknown"


def _safe_channel_id(ch: Optional[str]) -> str:
    if not ch:
        return ""
    return re.sub(r"[^0-9a-fA-F]", "", ch)


def _derive_streamer_id(channel_id: Optional[str], streamer_name: Optional[str]) -> str:
    if channel_id:
        safe = _safe_channel_id(channel_id)
        if safe:
            return f"channel-{safe}"
    if streamer_name:
        return f"name-{_slugify(streamer_name)}"
    return "unknown-streamer"


def _iso_from_publish_date(raw: str) -> str:
    if not raw:
        return ""
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(raw, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=KST)
            return dt.isoformat()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return raw


def _published_date_str(iso: str, fallback_from_fname: Optional[str] = None) -> str:
    if fallback_from_fname:
        return fallback_from_fname
    try:
        dt = datetime.fromisoformat(iso)
        return dt.strftime("%Y%m%d")
    except (ValueError, TypeError):
        return ""


_HEADER_TAG_RE = re.compile(r"[`#]+([\w가-힣]+)")


def _extract_search_text(streamer_name: str, title: str, md: str) -> str:
    tokens: list[str] = []
    if streamer_name:
        tokens.append(streamer_name)
    if title:
        tokens.append(title)

    m = re.search(r"핵심 요약[:\*\s]*(.+)", md or "")
    if m:
        tags = _HEADER_TAG_RE.findall(m.group(1))
        if tags:
            tokens.append(" ".join(f"#{t}" for t in tags))

    m = re.search(r'^\s*>\s*"?(.+?)"?\s*$', md or "", flags=re.M)
    if m:
        tokens.append(m.group(1).strip().strip('"'))

    tl = re.search(r"###\s*📍[^\n]*타임라인[^\n]*\n(.+?)(?=\n###\s|\Z)", md or "", flags=re.S)
    if tl:
        titles = re.findall(
            r"-\s*\*\*\s*\[\d{2}:\d{2}:\d{2}\]\s*(.+?)\*\*",
            tl.group(1),
        )
        tokens.extend(titles[:20])

    text = " | ".join(t for t in tokens if t)
    return text[:4000]


# ── 핵심 로직 ─────────────────────────────────────────────────

def _load_pipeline_config(project_root: Path) -> dict:
    path = project_root / "pipeline_config.json"
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def _find_vod_triples(output_dir: Path) -> list[tuple[Path, Path, Path]]:
    """output_dir 에서 (md, html, metadata.json) 3-tuple 을 모은다."""
    triples: list[tuple[Path, Path, Path]] = []
    if not output_dir.is_dir():
        return triples
    for meta_path in sorted(output_dir.glob("*_metadata.json")):
        base = meta_path.name[: -len("_metadata.json")]
        md_path = output_dir / f"{base}.md"
        html_path = output_dir / f"{base}.html"
        if md_path.exists() and html_path.exists():
            triples.append((md_path, html_path, meta_path))
    return triples


def _build_vod_record(
    md_path: Path,
    html_path: Path,
    meta_path: Path,
    pipeline_cfg: dict,
) -> VodRecord:
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)
    try:
        with open(md_path, "r", encoding="utf-8") as f:
            md_body = f.read()
    except OSError:
        md_body = ""

    video_no = str(meta.get("video_no") or "")
    title = (meta.get("title") or "").strip()
    channel_name = (meta.get("channel") or "").strip() or pipeline_cfg.get("streamer_name", "")
    # metadata channel_id 가 권위. 없으면 pipeline_config fallback (레거시).
    channel_id = meta.get("channel_id") or pipeline_cfg.get("target_channel_id") or None
    # metadata streamer_id 가 있으면 그대로 사용, 없으면 derive.
    streamer_id = meta.get("streamer_id") or _derive_streamer_id(channel_id, channel_name)

    published_raw = meta.get("publish_date") or ""
    published_at = _iso_from_publish_date(published_raw)

    fname_match = _VIDEO_FNAME_RE.match(meta_path.stem.replace("_metadata", ""))
    date_str_from_fname = fname_match.group("date") if fname_match else ""
    published_date_str = _published_date_str(published_at, fallback_from_fname=date_str_from_fname)

    duration = int(meta.get("duration") or 0)
    category = meta.get("category") or None
    total_chats = int(meta.get("total_chats") or 0)
    highlight_count = int(meta.get("highlight_count") or 0)

    search_text = _extract_search_text(channel_name, title, md_body)

    return VodRecord(
        streamer_id=streamer_id,
        streamer_name=channel_name,
        channel_id=channel_id,
        platform="chzzk",
        video_no=video_no,
        title=title,
        published_at=published_at,
        published_date_str=published_date_str,
        duration_sec=duration,
        platform_category=category,
        content_judgement=None,
        summary_md_path=f"vods/{video_no}/report.md",
        summary_html_path=f"vods/{video_no}/report.html",
        metadata_json_path=f"vods/{video_no}/metadata.json",
        thumbnail_url=None,
        search_text=search_text,
        stats={
            "total_chats": total_chats,
            "highlight_count": highlight_count,
        },
        processed_at=meta.get("processed_at") or "",
    )


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def _copy_into_site(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)


# 레거시 리포트 HTML 에 박혀있는 구 CDN URL 패턴.
# 구 summarizer template 이 박아넣은 chart.js CDN 및 Google Fonts @import 를
# 빌드 시점에 제거/치환해, site/ 에는 외부 CDN 참조가 남지 않도록 한다.
_LEGACY_CHARTJS_CDN_RE = re.compile(
    r'<script\s+src="https://cdn\.jsdelivr\.net/npm/chart\.js@[^"]+/dist/chart\.umd\.min\.js"\s*>\s*</script>',
    re.IGNORECASE,
)
_LEGACY_GFONTS_IMPORT_RE = re.compile(
    r"\s*@import\s+url\(['\"]https://fonts\.googleapis\.com/[^'\"]+['\"]\)\s*;",
    re.IGNORECASE,
)


def _rewrite_legacy_cdn_html(html_text: str) -> str:
    """구 버전 summarizer 가 생성한 리포트 HTML 의 외부 CDN 참조를 자가호스팅으로 치환한다.

    - chart.js CDN <script> → local vendored asset (../../assets/vendor/chart.umd.min.js)
    - Google Fonts @import → 주석 (로컬/시스템 폰트 fallback 으로 처리)

    본 리포트는 site/vods/<video_no>/report.html 로 배치되므로 relative path 는
    '../../' 로 고정된다.
    """
    out = _LEGACY_CHARTJS_CDN_RE.sub(
        '<script src="../../assets/vendor/chart.umd.min.js"></script>',
        html_text,
    )
    out = _LEGACY_GFONTS_IMPORT_RE.sub(
        "\n  /* Self-hosted assets: no external CDN. Fonts use OS-installed fallbacks. */",
        out,
    )
    return out


def _copy_report_html(src: Path, dst: Path) -> None:
    """리포트 HTML 을 읽어 legacy CDN 참조를 rewrite 한 뒤 site/ 로 기록한다."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(src, "r", encoding="utf-8") as f:
        raw = f.read()
    rewritten = _rewrite_legacy_cdn_html(raw)
    with open(dst, "w", encoding="utf-8", newline="") as f:
        f.write(rewritten)


def _assets_source_dir(project_root: Path) -> Path:
    return project_root / "publish" / "web"


def _copy_web_assets(project_root: Path, site_dir: Path) -> list[str]:
    """publish/web/ 의 정적 자산과 deploy meta 파일을 site/ 로 복사한다.

    deploy meta:
      - _redirects, _headers : Cloudflare Pages 용. 이름이 underscore 로
        시작하므로 GitHub Pages 에서 Jekyll 가 필터링하지 않도록 .nojekyll
        도 함께 복사한다.
      - .nojekyll : GitHub Pages compat. Cloudflare 에서는 무시된다.
    """
    src = _assets_source_dir(project_root)
    copied: list[str] = []
    if not src.is_dir():
        return copied
    for rel in (
        "index.html", "streamer.html", "vod.html", "search.html",
        "assets/app.css", "assets/app.js",
        "assets/vendor/chart.umd.min.js",
        "_redirects", "_headers", ".nojekyll",
    ):
        src_path = src / rel
        if src_path.exists():
            dst_path = site_dir / rel
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src_path, dst_path)
            copied.append(rel)
    return copied


def _stable_generated_at(records: list[VodRecord]) -> str:
    """Derive a deterministic site timestamp from the input records."""
    candidates = [rec.processed_at for rec in records if rec.processed_at]
    if candidates:
        return max(candidates)
    published = [rec.published_at for rec in records if rec.published_at]
    if published:
        return max(published)
    return ""


def build_site(
    output_dir: Path,
    site_dir: Path,
    project_root: Path,
) -> dict:
    """빌드를 수행하고 sanity 결과를 반환한다."""
    pipeline_cfg = _load_pipeline_config(project_root)
    triples = _find_vod_triples(output_dir)
    records: list[VodRecord] = [
        _build_vod_record(md, html, meta, pipeline_cfg)
        for md, html, meta in triples
    ]

    site_dir.mkdir(parents=True, exist_ok=True)

    # 각 VOD 디렉토리 + 파일 복사
    # report.html 은 legacy CDN 참조 rewrite 를 적용해 self-hosted 로 변환한다.
    for rec, (md, html, meta) in zip(records, triples):
        vod_dir = site_dir / "vods" / rec.video_no
        _copy_into_site(md, vod_dir / "report.md")
        _copy_report_html(html, vod_dir / "report.html")
        _copy_into_site(meta, vod_dir / "metadata.json")
        _write_json(vod_dir / "index.json", rec.to_public_dict())

    # 스트리머별 index + 글로벌 streamers.json
    streamers: dict[str, StreamerRef] = {}
    per_streamer_rows: dict[str, list[dict]] = {}
    for rec in records:
        ref = streamers.get(rec.streamer_id)
        if ref is None:
            ref = StreamerRef(
                streamer_id=rec.streamer_id,
                streamer_name=rec.streamer_name,
                channel_id=rec.channel_id,
                platform=rec.platform,
                vod_count=0,
            )
            streamers[rec.streamer_id] = ref
            per_streamer_rows[rec.streamer_id] = []
        ref.vod_count += 1
        per_streamer_rows[rec.streamer_id].append({
            "video_no": rec.video_no,
            "title": rec.title,
            "published_at": rec.published_at,
            "published_date_str": rec.published_date_str,
            "duration_sec": rec.duration_sec,
            "platform_category": rec.platform_category,
            "stats": rec.stats,
        })

    for sid, ref in streamers.items():
        rows = sorted(
            per_streamer_rows[sid],
            key=lambda r: r.get("published_at") or "",
            reverse=True,
        )
        _write_json(site_dir / "streamers" / sid / "index.json", {
            "streamer": asdict(ref),
            "vods": rows,
        })

    # 글로벌 인덱스
    _write_json(site_dir / "streamers.json", [asdict(s) for s in streamers.values()])
    from datetime import datetime, timezone
    _built_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _write_json(site_dir / "index.json", {
        "generated_at": _built_at,
        "built_at": _built_at,
        "latest_processed_at": _stable_generated_at(records),
        "total_streamers": len(streamers),
        "total_vods": len(records),
        "streamers": [asdict(s) for s in streamers.values()],
    })

    # 검색 인덱스
    search_rows = [
        {
            "video_no": rec.video_no,
            "streamer_id": rec.streamer_id,
            "streamer_name": rec.streamer_name,
            "title": rec.title,
            "published_at": rec.published_at,
            "search_text": rec.search_text,
        }
        for rec in records
    ]
    _write_json(site_dir / "search-index.json", search_rows)

    # 웹 에셋 복사
    assets_copied = _copy_web_assets(project_root, site_dir)

    return {
        "vod_count": len(records),
        "streamer_count": len(streamers),
        "assets_copied": assets_copied,
        "site_dir": str(site_dir),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="멀티 스트리머 정적 사이트 빌더")
    parser.add_argument("--output-dir", default="./output",
                        help="기존 파이프라인 출력 디렉토리 (기본: ./output)")
    parser.add_argument("--site-dir", default="./site",
                        help="정적 사이트 출력 디렉토리 (기본: ./site)")
    parser.add_argument("--project-root", default=str(_PROJECT_ROOT),
                        help="프로젝트 루트 (pipeline_config.json 위치)")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    result = build_site(
        output_dir=Path(args.output_dir).resolve(),
        site_dir=Path(args.site_dir).resolve(),
        project_root=project_root,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["vod_count"] > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
