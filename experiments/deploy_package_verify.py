"""End-to-end verifier for the deploy bundle command (publish.deploy.package).

Runs against the *real* built ``site/`` directory (no mocks). Each test group
is independent and emits a single PASS/FAIL line. Group summary at the bottom.

Coverage:
    T1 real_bundles_built       - package against real site/, expect 1 zip + 1 tgz.
    T2 zip_top_level_layout     - cloudflare zip stores entries at the publish root
                                  (index.html, _redirects, _headers, .nojekyll).
    T3 tgz_top_level_layout     - github-pages tar.gz stores entries at root and
                                  expands cleanly with deterministic mtimes.
    T4 preflight_blocks         - injecting NID_AUT into a copied site causes
                                  package() to abort with no archive written.
    T5 strict_blocks_warnings   - removing _headers from a copied site:
                                    non-strict still builds bundles,
                                    strict aborts with no archive written.
    T6 idempotent_bytes         - two runs against the same site produce
                                  byte-identical archives (sha256 match).
    T7 archive_cookie_grep      - every entry inside every produced archive
                                  contains zero NID_AUT/NID_SES hits.

Usage:
    python -m experiments.deploy_package_verify
    python experiments/deploy_package_verify.py --site-dir ./site
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from publish.deploy.package import (
    KNOWN_TARGETS,
    _BUNDLE_FILENAMES,
    _TAR_FIXED_MTIME,
    _ZIP_FIXED_DATE,
    package,
)


COOKIE_RES = (re.compile(r"NID_AUT"), re.compile(r"NID_SES"))


def _print(line: str) -> None:
    payload = f"{line}\n"
    stream = sys.stdout
    encoding = getattr(stream, "encoding", None) or "utf-8"
    try:
        stream.write(payload)
    except UnicodeEncodeError:
        stream.buffer.write(payload.encode(encoding, errors="replace"))


def _copy_site(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def _t1_t2_t3_real_bundles(site_dir: Path, work: Path) -> tuple[bool, str]:
    out_dir = work / "out_real"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    result = package(site_dir, out_dir, targets=("all",))
    if result.aborted_reason:
        return False, f"unexpected abort: {result.aborted_reason}"
    if len(result.bundles) != 2:
        return False, f"expected 2 bundles, got {len(result.bundles)}"
    if {b.target for b in result.bundles} != set(KNOWN_TARGETS):
        return False, f"target set mismatch: {[b.target for b in result.bundles]}"

    cf_path = out_dir / "cloudflare" / _BUNDLE_FILENAMES["cloudflare"]
    gh_path = out_dir / "github-pages" / _BUNDLE_FILENAMES["github-pages"]
    if not cf_path.is_file():
        return False, f"cloudflare archive missing: {cf_path}"
    if not gh_path.is_file():
        return False, f"github-pages archive missing: {gh_path}"

    expected_top = {"index.html", "index.json", "_redirects", "_headers", ".nojekyll"}

    # T2 - zip layout
    with zipfile.ZipFile(cf_path) as zf:
        zip_names = set(zf.namelist())
        zip_dates = {zi.date_time for zi in zf.infolist()}
    missing_zip = expected_top - zip_names
    if missing_zip:
        return False, f"zip missing top-level entries: {sorted(missing_zip)}"
    if any(name.startswith("site/") for name in zip_names):
        return False, "zip contains entries nested under site/"
    if zip_dates != {_ZIP_FIXED_DATE}:
        return False, f"zip date_time non-deterministic: {sorted(zip_dates)}"

    # T3 - tar.gz layout
    with tarfile.open(gh_path, "r:gz") as tf:
        members = tf.getmembers()
    tar_names = {m.name for m in members}
    missing_tar = expected_top - tar_names
    if missing_tar:
        return False, f"tar.gz missing top-level entries: {sorted(missing_tar)}"
    if any(m.name.startswith("site/") for m in members):
        return False, "tar.gz contains entries nested under site/"
    bad_mtimes = {m.mtime for m in members if m.mtime != _TAR_FIXED_MTIME}
    if bad_mtimes:
        return False, f"tar.gz mtimes non-deterministic: {sorted(bad_mtimes)[:5]}"
    bad_uids = {(m.uid, m.gid, m.uname, m.gname) for m in members
                if (m.uid, m.gid, m.uname, m.gname) != (0, 0, "", "")}
    if bad_uids:
        return False, f"tar.gz ownership non-deterministic: {sorted(bad_uids)[:5]}"

    # manifest + checksums
    if result.manifest_path is None or not result.manifest_path.is_file():
        return False, "manifest.json missing"
    if result.checksums_path is None or not result.checksums_path.is_file():
        return False, "checksums.txt missing"
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    if set(manifest.get("targets") or []) != set(KNOWN_TARGETS):
        return False, f"manifest targets mismatch: {manifest.get('targets')}"
    if not manifest.get("bundles"):
        return False, "manifest.bundles empty"
    checks = result.checksums_path.read_text(encoding="utf-8").strip().splitlines()
    if len(checks) != 2:
        return False, f"checksums.txt expected 2 lines, got {len(checks)}"
    for line in checks:
        sha, _, name = line.partition("  ")
        if len(sha) != 64:
            return False, f"checksums sha length wrong: {line}"
        if not name:
            return False, f"checksums missing path: {line}"
    return True, (
        f"cf={cf_path.name}({len(zip_names)} entries) "
        f"gh={gh_path.name}({len(tar_names)} entries)"
    )


def _t4_preflight_blocks(site_dir: Path, work: Path) -> tuple[bool, str]:
    poisoned_site = work / "site_poisoned"
    out_dir = work / "out_poisoned"
    _copy_site(site_dir, poisoned_site)
    # poison: append a plain cookie token and an escaped JSON-string token.
    target = poisoned_site / "search-index.json"
    text = target.read_text(encoding="utf-8")
    target.write_text(
        text + '\n// NID_AUT injected for verifier\n"line1\\\\nNID_SES\\\\nline2"\n',
        encoding="utf-8",
    )

    if out_dir.exists():
        shutil.rmtree(out_dir)
    result = package(poisoned_site, out_dir, targets=("cloudflare",))
    if result.aborted_reason is None:
        return False, "expected abort due to preflight cookie leak, but bundles built"
    if result.bundles:
        return False, f"expected 0 bundles after abort, got {len(result.bundles)}"
    cf_path = out_dir / "cloudflare" / _BUNDLE_FILENAMES["cloudflare"]
    if cf_path.exists():
        return False, f"cloudflare archive should not exist after abort: {cf_path}"
    return True, f"abort_reason={result.aborted_reason[:60]}..."


def _t5_strict_blocks_warnings(site_dir: Path, work: Path) -> tuple[bool, str]:
    warn_site = work / "site_no_headers"
    _copy_site(site_dir, warn_site)
    headers_file = warn_site / "_headers"
    if headers_file.exists():
        headers_file.unlink()

    # Non-strict run must still produce a bundle (warning only).
    out_lax = work / "out_lax"
    if out_lax.exists():
        shutil.rmtree(out_lax)
    res_lax = package(warn_site, out_lax, targets=("cloudflare",), strict=False)
    if res_lax.aborted_reason:
        return False, f"non-strict should not abort on warnings: {res_lax.aborted_reason}"
    if not res_lax.preflight.warnings:
        return False, "non-strict run produced no preflight warnings; setup is wrong"
    if not res_lax.bundles:
        return False, "non-strict run produced no bundles"

    # Strict run must abort.
    out_strict = work / "out_strict"
    if out_strict.exists():
        shutil.rmtree(out_strict)
    res_strict = package(warn_site, out_strict, targets=("cloudflare",), strict=True)
    if res_strict.aborted_reason is None:
        return False, "strict run did not abort despite warnings"
    if res_strict.bundles:
        return False, f"strict run produced {len(res_strict.bundles)} bundles; expected 0"
    cf_path = out_strict / "cloudflare" / _BUNDLE_FILENAMES["cloudflare"]
    if cf_path.exists():
        return False, "strict run should not have written archive file"
    return True, (
        f"lax_warnings={len(res_lax.preflight.warnings)} "
        f"strict_abort={res_strict.aborted_reason[:50]}..."
    )


def _t6_idempotent(site_dir: Path, work: Path) -> tuple[bool, str]:
    out_a = work / "out_idem_a"
    out_b = work / "out_idem_b"
    for d in (out_a, out_b):
        if d.exists():
            shutil.rmtree(d)
    res_a = package(site_dir, out_a, targets=("all",))
    res_b = package(site_dir, out_b, targets=("all",))
    if res_a.aborted_reason or res_b.aborted_reason:
        return False, f"unexpected abort a={res_a.aborted_reason} b={res_b.aborted_reason}"
    sums_a = {b.target: b.sha256 for b in res_a.bundles}
    sums_b = {b.target: b.sha256 for b in res_b.bundles}
    if sums_a != sums_b:
        diffs = [t for t in sums_a if sums_a.get(t) != sums_b.get(t)]
        return False, f"sha256 mismatch on targets: {diffs}"
    return True, " ".join(f"{t}={s[:12]}" for t, s in sums_a.items())


def _t7_archive_cookie_grep(site_dir: Path, work: Path) -> tuple[bool, str]:
    out_dir = work / "out_cookie"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    result = package(site_dir, out_dir, targets=("all",))
    if result.aborted_reason:
        return False, f"unexpected abort: {result.aborted_reason}"

    hits: list[str] = []

    cf_path = out_dir / "cloudflare" / _BUNDLE_FILENAMES["cloudflare"]
    with zipfile.ZipFile(cf_path) as zf:
        for name in zf.namelist():
            try:
                data = zf.read(name)
            except (KeyError, RuntimeError):
                continue
            text = data.decode("utf-8", errors="replace")
            for pat in COOKIE_RES:
                if pat.search(text):
                    hits.append(f"cf:{name}")
                    break

    gh_path = out_dir / "github-pages" / _BUNDLE_FILENAMES["github-pages"]
    with tarfile.open(gh_path, "r:gz") as tf:
        for member in tf.getmembers():
            if not member.isreg():
                continue
            f = tf.extractfile(member)
            if f is None:
                continue
            text = f.read().decode("utf-8", errors="replace")
            for pat in COOKIE_RES:
                if pat.search(text):
                    hits.append(f"gh:{member.name}")
                    break

    if hits:
        return False, f"cookie hits in archives: {hits}"
    return True, "0 hits across both archives"


TESTS = [
    ("T1+T2+T3 real_bundles_built+layout", _t1_t2_t3_real_bundles),
    ("T4 preflight_blocks_on_cookie_leak", _t4_preflight_blocks),
    ("T5 strict_blocks_warnings",          _t5_strict_blocks_warnings),
    ("T6 idempotent_bytes",                _t6_idempotent),
    ("T7 archive_cookie_grep",             _t7_archive_cookie_grep),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Deploy bundle command verifier.")
    parser.add_argument("--site-dir", default="./site",
                        help="Path to the built site directory (default: ./site).")
    args = parser.parse_args()

    site_dir = Path(args.site_dir).resolve()
    if not site_dir.is_dir():
        _print(f"FAIL: site dir not found: {site_dir}")
        return 1

    fails = 0
    with tempfile.TemporaryDirectory(prefix="deploy_pkg_verify_") as td:
        work = Path(td)
        for name, fn in TESTS:
            try:
                ok, detail = fn(site_dir, work)
            except Exception as e:
                ok, detail = False, f"exception: {e!r}"
            tag = "PASS" if ok else "FAIL"
            _print(f"  {tag}  {name}: {detail}")
            if not ok:
                fails += 1

    _print("")
    _print(f"deploy_package_verify: {len(TESTS) - fails}/{len(TESTS)} passed, {fails} failed")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
