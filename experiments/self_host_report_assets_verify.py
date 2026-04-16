"""End-to-end verifier for the self-hosted report assets slice.

This verifier proves that, after the session 2026-04-17-self-host-report-assets
implementation, per-VOD report HTML no longer loads any external CDN and that
``publish.deploy.check --strict`` + ``publish.deploy.package --strict --target all``
both pass on the real built ``site/`` tree.

Each group is independent and emits a single PASS/FAIL line. Group summary is
emitted at the end. The script runs against the *real* ``site/`` tree (no
mocks); T3/T4/T5 use isolated tempdirs so the working tree is never polluted.

Coverage:
    T1 report_html_no_cdn      - every site/vods/<id>/report.html has zero
                                 external http(s) refs and references the local
                                 ../../assets/vendor/chart.umd.min.js.
    T2 vendor_asset_deployed   - site/assets/vendor/chart.umd.min.js exists and
                                 sha256 matches the source in publish/web/.
    T3 strict_preflight_pass   - ``python -m publish.deploy.check --strict``
                                 exits 0 against the real site/ tree (after a
                                 fresh build_site run).
    T4 strict_package_pass     - ``python -m publish.deploy.package --strict
                                 --target all --clean`` exits 0 against the
                                 real site/ and produces both bundles.
    T5 local_serve_smoke       - spin up ``http.server`` on a tempdir copy of
                                 site/, confirm 200 for index.html, vod.html,
                                 the report.html, and the vendored asset.
    T6 cookie_grep             - ``NID_AUT``/``NID_SES`` substring scan across
                                 the whole site/ tree returns zero hits.

Usage:
    python experiments/self_host_report_assets_verify.py
    python experiments/self_host_report_assets_verify.py --site-dir ./site
    python experiments/self_host_report_assets_verify.py --skip-rebuild
"""
from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# Non-allow-listed https reference inside an HTML body is a failure for T1.
# schema.org / w3.org are structured-data namespaces, not runtime CDN fetches,
# and the preflight scanner already treats them as benign.
_ALLOWLISTED_URL_PREFIXES = (
    "https://schema.org",
    "https://www.w3.org",
)
_EXTERNAL_URL_RE = re.compile(r"https?://[^\"'\s)<>]+")


def _print(line: str) -> None:
    payload = f"{line}\n"
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


def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _sniff_external_urls(text: str) -> list[str]:
    hits: list[str] = []
    for match in _EXTERNAL_URL_RE.finditer(text):
        url = match.group(0)
        if any(url.startswith(prefix) for prefix in _ALLOWLISTED_URL_PREFIXES):
            continue
        hits.append(url)
    return hits


def _run_subprocess(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _maybe_rebuild_site(project_root: Path, site_dir: Path, output_dir: Path) -> tuple[bool, str]:
    """Rebuild site/ from output/ so the current code path is exercised.

    Returns (ok, tail_of_stderr).
    """
    cmd = [
        sys.executable,
        "-m",
        "publish.builder.build_site",
        "--output-dir",
        str(output_dir),
        "--site-dir",
        str(site_dir),
        "--project-root",
        str(project_root),
    ]
    proc = _run_subprocess(cmd, cwd=project_root)
    return proc.returncode == 0, (proc.stderr or "")[-400:]


def t1_report_html_no_cdn(site_dir: Path) -> tuple[bool, str]:
    """Every site/vods/<id>/report.html must be CDN-free + use local chart."""
    vods_dir = site_dir / "vods"
    if not vods_dir.is_dir():
        return False, "site/vods/ directory missing"
    reports = sorted(vods_dir.glob("*/report.html"))
    if not reports:
        return False, "no site/vods/<id>/report.html found"

    problems: list[str] = []
    for report in reports:
        text = report.read_text(encoding="utf-8", errors="replace")
        external = _sniff_external_urls(text)
        if external:
            problems.append(
                f"{report.relative_to(site_dir)}: external refs {external[:3]}"
            )
        if "../../assets/vendor/chart.umd.min.js" not in text:
            problems.append(
                f"{report.relative_to(site_dir)}: local chart.js ref missing"
            )
        if "@import url('https://fonts.googleapis.com" in text:
            problems.append(
                f"{report.relative_to(site_dir)}: Google Fonts @import still present"
            )
    if problems:
        return False, "; ".join(problems[:4])
    return True, f"{len(reports)} report(s) CDN-free"


def t2_vendor_asset_deployed(project_root: Path, site_dir: Path) -> tuple[bool, str]:
    """site/assets/vendor/chart.umd.min.js must exist and match publish/web/ src."""
    deployed = site_dir / "assets" / "vendor" / "chart.umd.min.js"
    source = project_root / "publish" / "web" / "assets" / "vendor" / "chart.umd.min.js"
    if not source.is_file():
        return False, f"source vendor asset missing: {source}"
    if not deployed.is_file():
        return False, f"deployed vendor asset missing: {deployed}"
    src_hash = _sha256_of_file(source)
    dst_hash = _sha256_of_file(deployed)
    if src_hash != dst_hash:
        return False, f"sha256 mismatch src={src_hash[:12]} dst={dst_hash[:12]}"
    return True, f"sha256={src_hash[:16]}, size={deployed.stat().st_size}"


def t3_strict_preflight_pass(project_root: Path, site_dir: Path) -> tuple[bool, str]:
    cmd = [
        sys.executable,
        "-m",
        "publish.deploy.check",
        "--site-dir",
        str(site_dir),
        "--strict",
        "--json",
    ]
    proc = _run_subprocess(cmd, cwd=project_root)
    if proc.returncode != 0:
        # Keep the tail of stdout (json) for diagnostics.
        tail = (proc.stdout or "")[-400:].replace("\n", " ")
        return False, f"exit={proc.returncode}; {tail}"
    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return False, "preflight JSON unparseable"
    warnings = report.get("warnings") or []
    if warnings:
        return False, f"warnings present under --strict: {warnings[:2]}"
    return True, f"exit=0, warnings=0, errors=0, vods={report.get('info',{}).get('total_vods', '?')}"


def t4_strict_package_pass(project_root: Path) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix="selfhost_pkg_") as tmpdir:
        out_dir = Path(tmpdir) / "dist-deploy"
        cmd = [
            sys.executable,
            "-m",
            "publish.deploy.package",
            "--target",
            "all",
            "--clean",
            "--strict",
            "--out-dir",
            str(out_dir),
            "--json",
        ]
        proc = _run_subprocess(cmd, cwd=project_root)
        if proc.returncode != 0:
            tail = (proc.stdout or "")[-300:].replace("\n", " ")
            err = (proc.stderr or "")[-300:].replace("\n", " ")
            return False, f"exit={proc.returncode}; stdout={tail}; stderr={err}"
        cf_zip = out_dir / "cloudflare" / "site-upload.zip"
        gh_tgz = out_dir / "github-pages" / "site-artifact.tar.gz"
        manifest = out_dir / "manifest.json"
        checksums = out_dir / "checksums.txt"
        missing = [
            str(p.relative_to(out_dir)) for p in (cf_zip, gh_tgz, manifest, checksums)
            if not p.is_file()
        ]
        if missing:
            return False, f"bundle outputs missing: {missing}"
        return True, (
            f"cloudflare={cf_zip.stat().st_size}B, "
            f"github-pages={gh_tgz.stat().st_size}B"
        )


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002
        return


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def t5_local_serve_smoke(site_dir: Path) -> tuple[bool, str]:
    """Serve a tempdir copy of site/ and GET the key paths."""
    reports = sorted((site_dir / "vods").glob("*/report.html"))
    if not reports:
        return False, "no report.html to exercise"
    sample = reports[0]
    video_no = sample.parent.name

    with tempfile.TemporaryDirectory(prefix="selfhost_serve_") as tmpdir:
        root = Path(tmpdir) / "site"
        shutil.copytree(site_dir, root)

        port = _find_free_port()
        handler_cls = type(
            "_RootedHandler",
            (_QuietHandler,),
            {"directory": str(root)},
        )

        def _make_handler(*args, **kwargs):
            return handler_cls(*args, directory=str(root), **kwargs)

        httpd = HTTPServer(("127.0.0.1", port), _make_handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            # Settle the listener.
            time.sleep(0.1)
            targets = [
                "/index.html",
                "/vod.html",
                f"/vods/{video_no}/report.html",
                "/assets/vendor/chart.umd.min.js",
            ]
            statuses: dict[str, int] = {}
            for path in targets:
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
                try:
                    conn.request("GET", path)
                    resp = conn.getresponse()
                    statuses[path] = resp.status
                    resp.read()
                finally:
                    conn.close()
            bad = {p: s for p, s in statuses.items() if s != 200}
            if bad:
                return False, f"non-200 responses: {bad}"
            return True, f"200 for {len(statuses)} endpoints (port={port})"
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)


def t6_cookie_grep(site_dir: Path) -> tuple[bool, str]:
    hits: list[str] = []
    for path in site_dir.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {
            ".html", ".htm", ".json", ".js", ".css", ".md", ".txt"
        }:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "NID_AUT" in text or "NID_SES" in text:
            hits.append(str(path.relative_to(site_dir)))
    if hits:
        return False, f"cookie tokens in {hits[:3]}"
    return True, "0 NID_AUT/NID_SES across site/"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="End-to-end verifier for self-hosted report assets."
    )
    parser.add_argument(
        "--site-dir",
        default=str(_PROJECT_ROOT / "site"),
        help="Path to the built site/ directory (default: <project>/site)",
    )
    parser.add_argument(
        "--output-dir",
        default=str(_PROJECT_ROOT / "output"),
        help="Path to the pipeline output/ directory (default: <project>/output)",
    )
    parser.add_argument(
        "--skip-rebuild",
        action="store_true",
        help="Do not re-run build_site; use whatever is currently on disk.",
    )
    args = parser.parse_args()

    project_root = _PROJECT_ROOT
    site_dir = Path(args.site_dir).resolve()
    output_dir = Path(args.output_dir).resolve()

    if not args.skip_rebuild:
        _print("[build] rebuilding site/ via publish.builder.build_site ...")
        ok, tail = _maybe_rebuild_site(project_root, site_dir, output_dir)
        if not ok:
            _print(f"[build] FAIL (stderr tail: {tail})")
            return 1
        _print("[build] OK")

    groups = (
        ("T1 report_html_no_cdn", lambda: t1_report_html_no_cdn(site_dir)),
        ("T2 vendor_asset_deployed", lambda: t2_vendor_asset_deployed(project_root, site_dir)),
        ("T3 strict_preflight_pass", lambda: t3_strict_preflight_pass(project_root, site_dir)),
        ("T4 strict_package_pass", lambda: t4_strict_package_pass(project_root)),
        ("T5 local_serve_smoke", lambda: t5_local_serve_smoke(site_dir)),
        ("T6 cookie_grep", lambda: t6_cookie_grep(site_dir)),
    )

    results: list[tuple[str, bool, str]] = []
    for label, fn in groups:
        try:
            ok, note = fn()
        except Exception as exc:  # noqa: BLE001
            ok, note = False, f"EXC {type(exc).__name__}: {exc}"
        status = "PASS" if ok else "FAIL"
        results.append((label, ok, note))
        _print(f"{status} {label}: {note}")

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    _print("")
    _print(f"SUMMARY: {passed}/{total} groups PASS")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
