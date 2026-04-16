"""Deploy preflight check for the generated static site.

Checks:
  1. Required HTML pages: index.html, streamer.html, vod.html, search.html
  2. Required JSON globals: index.json, streamers.json, search-index.json
  3. Required asset bundle: assets/app.css, assets/app.js
  4. Cloudflare Pages deploy meta: _redirects, _headers (warning-level)
  5. GitHub Pages compat: .nojekyll (warning-level)
  6. Streamer/VOD presence: at least 1 streamer and 1 VOD record
  7. Cookie leak scan: NID_AUT / NID_SES not present in any text file
  8. Absolute path leakage: no Windows drive letters or POSIX home paths
  9. External CDN dependency scan: warns if HTML/CSS/JS references an http(s)
     resource (advisory only)

CLI:
    python -m publish.deploy.check
    python -m publish.deploy.check --site-dir ./site
    python -m publish.deploy.check --strict

Library:
    from publish.deploy.check import preflight, PreflightResult
    result = preflight(Path("./site"))
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


REQUIRED_HTML = ("index.html", "streamer.html", "vod.html", "search.html")
REQUIRED_JSON = ("index.json", "streamers.json", "search-index.json")
REQUIRED_ASSETS = ("assets/app.css", "assets/app.js")
DEPLOY_META_CF = ("_redirects", "_headers")
DEPLOY_META_GH = (".nojekyll",)

# Cookie key names should be treated as toxic anywhere in text payloads.
# Word-boundary-only matching misses escaped JSON fragments such as
# "line1\\nNID_SES\\nline2", so use direct token detection.
COOKIE_PATTERNS = (
    re.compile(r"NID_AUT"),
    re.compile(r"NID_SES"),
)
ABSOLUTE_PATH_PATTERNS = (
    re.compile(r"[A-Za-z]:\\\\"),
    re.compile(r"[A-Za-z]:/(?:Users|github|home)"),
    re.compile(r"/home/[A-Za-z0-9_-]+/"),
    re.compile(r"/Users/[A-Za-z0-9_-]+/"),
)
EXTERNAL_URL_PATTERN = re.compile(r"https?://[^\"'\s)<>]+")


@dataclass
class PreflightResult:
    site_dir: Path
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    info: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {
            "site_dir": str(self.site_dir),
            "ok": self.ok,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "info": self.info,
        }


def _iter_text_files(site_dir: Path) -> Iterable[Path]:
    text_suffixes = {".html", ".htm", ".json", ".js", ".css", ".md", ".txt"}
    for path in site_dir.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() in text_suffixes:
            yield path


def _check_required(site_dir: Path, rels: Iterable[str], category: str, result: PreflightResult) -> None:
    missing = [rel for rel in rels if not (site_dir / rel).is_file()]
    if missing:
        result.errors.append(f"{category} missing: {missing}")


def _check_optional(site_dir: Path, rels: Iterable[str], category: str, result: PreflightResult) -> None:
    missing = [rel for rel in rels if not (site_dir / rel).exists()]
    if missing:
        result.warnings.append(f"{category} missing: {missing}")


def _check_index_counts(site_dir: Path, result: PreflightResult) -> None:
    idx_path = site_dir / "index.json"
    if not idx_path.is_file():
        return
    try:
        with open(idx_path, "r", encoding="utf-8") as f:
            idx = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        result.errors.append(f"index.json unreadable: {e}")
        return

    streamers = idx.get("total_streamers", 0)
    vods = idx.get("total_vods", 0)
    result.info["total_streamers"] = streamers
    result.info["total_vods"] = vods

    if streamers < 1:
        result.errors.append(f"index.json.total_streamers < 1 (got {streamers}); site is empty")
    if vods < 1:
        result.errors.append(f"index.json.total_vods < 1 (got {vods}); site is empty")


def _check_cookie_leak(site_dir: Path, result: PreflightResult) -> None:
    leaks: list[str] = []
    for path in _iter_text_files(site_dir):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            result.warnings.append(f"unreadable file skipped: {path.relative_to(site_dir)} ({e})")
            continue
        for pat in COOKIE_PATTERNS:
            if pat.search(text):
                leaks.append(str(path.relative_to(site_dir)))
                break
    if leaks:
        result.errors.append(f"COOKIE LEAK: NID_AUT/NID_SES detected in: {leaks}")


def _check_absolute_paths(site_dir: Path, result: PreflightResult) -> None:
    leaks: list[str] = []
    for path in _iter_text_files(site_dir):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for pat in ABSOLUTE_PATH_PATTERNS:
            if pat.search(text):
                leaks.append(f"{path.relative_to(site_dir)}: {pat.pattern}")
                break
    if leaks:
        result.warnings.append(f"absolute path mention(s): {leaks}")


def _check_external_cdn(site_dir: Path, result: PreflightResult) -> None:
    """Warn on http(s) refs in HTML/CSS/JS that imply a runtime CDN fetch.

    Vendored third-party assets under ``assets/vendor/`` are excluded: they are
    self-hosted by definition and any http(s) string inside their minified
    payload is an inert documentation/license URL (chartjs.org homepage,
    jsdelivr.com docs page, color library readme), not a runtime network call.
    The cookie-leak and absolute-path scanners still run over those files.
    """
    cdn_hits: list[str] = []
    vendor_dir = site_dir / "assets" / "vendor"
    for path in site_dir.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".html", ".css", ".js"}:
            continue
        try:
            path.relative_to(vendor_dir)
        except ValueError:
            pass  # not under assets/vendor/, scan normally
        else:
            continue  # vendored asset, skip CDN scan
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in EXTERNAL_URL_PATTERN.finditer(text):
            url = match.group(0)
            if url.startswith("https://schema.org") or url.startswith("https://www.w3.org"):
                continue
            cdn_hits.append(f"{path.relative_to(site_dir)} -> {url}")
    if cdn_hits:
        result.warnings.append(f"external URL reference(s); verify network policy: {cdn_hits[:10]}")
        result.info["external_url_count"] = len(cdn_hits)


def preflight(site_dir: Path) -> PreflightResult:
    """Run all checks against the given built site directory."""
    result = PreflightResult(site_dir=site_dir.resolve())

    if not site_dir.is_dir():
        result.errors.append(f"site_dir does not exist or is not a directory: {site_dir}")
        return result

    _check_required(site_dir, REQUIRED_HTML, "HTML pages", result)
    _check_required(site_dir, REQUIRED_JSON, "JSON globals", result)
    _check_required(site_dir, REQUIRED_ASSETS, "asset bundle", result)
    _check_optional(site_dir, DEPLOY_META_CF, "Cloudflare deploy meta", result)
    _check_optional(site_dir, DEPLOY_META_GH, "GitHub Pages compat", result)
    _check_index_counts(site_dir, result)
    _check_cookie_leak(site_dir, result)
    _check_absolute_paths(site_dir, result)
    _check_external_cdn(site_dir, result)

    return result


def _emit_line(text: str) -> None:
    """Write one line without crashing on a narrow console encoding."""
    payload = f"{text}\n"
    stream = sys.stdout
    encoding = getattr(stream, "encoding", None) or "utf-8"
    try:
        stream.write(payload)
    except UnicodeEncodeError:
        encoded = payload.encode(encoding, errors="replace")
        if hasattr(stream, "buffer"):
            stream.buffer.write(encoded)
        else:
            stream.write(encoded.decode(encoding, errors="replace"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Static site deploy preflight.")
    parser.add_argument(
        "--site-dir",
        default="./site",
        help="Path to the built site directory (default: ./site)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as failures (exit 2 when any warning is present).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of human text.",
    )
    args = parser.parse_args()

    site = Path(args.site_dir).resolve()
    result = preflight(site)

    if args.json:
        _emit_line(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        _emit_line(f"Preflight on: {result.site_dir}")
        _emit_line(f"  total_streamers: {result.info.get('total_streamers', '?')}")
        _emit_line(f"  total_vods:      {result.info.get('total_vods', '?')}")
        if result.errors:
            _emit_line("ERRORS:")
            for error in result.errors:
                _emit_line(f"  - {error}")
        if result.warnings:
            _emit_line("WARNINGS:")
            for warning in result.warnings:
                _emit_line(f"  - {warning}")
        if result.ok and not result.warnings:
            _emit_line("OK - deploy preflight clean.")
        elif result.ok:
            _emit_line("OK with warnings.")
        else:
            _emit_line("FAIL - deploy blocked.")

    if result.errors:
        return 1
    if args.strict and result.warnings:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
