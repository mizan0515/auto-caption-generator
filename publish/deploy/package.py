"""Deploy bundle packager for the generated static site.

Reads ``site/`` (built by ``publish.builder.build_site``) and writes upload-ready
deploy bundles for one or more free hosting targets. Runs preflight first; if
preflight reports any error, no bundle file is written. ``--strict`` promotes
preflight warnings to the same blocking semantics.

Targets:
    cloudflare    - single zip suitable for Cloudflare Pages Direct Upload.
    github-pages  - single tar.gz suitable for the upload-pages-artifact action
                    (the action accepts an arbitrary tar.gz that expands into
                    the publish root).

Output layout::

    dist/deploy/
      cloudflare/
        site-upload.zip
      github-pages/
        site-artifact.tar.gz
      manifest.json
      checksums.txt

CLI:
    python -m publish.deploy.package
    python -m publish.deploy.package --target cloudflare
    python -m publish.deploy.package --target cloudflare --target github-pages
    python -m publish.deploy.package --target all --strict
    python -m publish.deploy.package --rebuild
    python -m publish.deploy.package --json

Library:
    from publish.deploy.package import package, PackageResult
    result = package(Path("./site"), Path("./dist/deploy"), targets=("cloudflare",))

Notes:
  * Bundles are deterministic across re-runs (fixed mtimes, sorted entries,
    no gzip header timestamp). Two invocations against the same ``site/`` must
    produce byte-identical archives.
  * Defense-in-depth: even after preflight passes, every archive entry is
    re-scanned for ``NID_AUT`` / ``NID_SES`` cookie names; any hit aborts.
  * Atomic writes: archives are first written to ``*.tmp`` and ``replace``-d
    into place so a partial bundle never lingers.
  * Does not touch the source ``site/`` tree, never reads ``pipeline_config.json``,
    never contacts a real host.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tarfile
import zipfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Iterable, Sequence

from publish.deploy.check import (
    COOKIE_PATTERNS,
    PreflightResult,
    _emit_line,
    preflight,
)

KNOWN_TARGETS: tuple[str, ...] = ("cloudflare", "github-pages")
DEFAULT_TARGETS: tuple[str, ...] = KNOWN_TARGETS
DEFAULT_OUT_DIR = Path("./dist/deploy")

# zip cannot represent epoch 0; use earliest representable date.
_ZIP_FIXED_DATE = (1980, 1, 1, 0, 0, 0)
# tar epoch: 1980-01-01 00:00:00 UTC -> seconds since 1970-01-01.
_TAR_FIXED_MTIME = 315532800

_BUNDLE_FILENAMES = {
    "cloudflare": "site-upload.zip",
    "github-pages": "site-artifact.tar.gz",
}


@dataclass
class BundleArtifact:
    target: str
    archive_path: Path
    archive_relpath: str
    file_count: int
    total_uncompressed_bytes: int
    sha256: str

    def to_dict(self) -> dict:
        d = asdict(self)
        d["archive_path"] = str(self.archive_path)
        return d


@dataclass
class PackageResult:
    site_dir: Path
    out_dir: Path
    targets_requested: list[str]
    preflight: PreflightResult
    bundles: list[BundleArtifact] = field(default_factory=list)
    manifest_path: Path | None = None
    checksums_path: Path | None = None
    aborted_reason: str | None = None
    rebuilt: bool = False

    @property
    def ok(self) -> bool:
        return self.aborted_reason is None and bool(self.bundles)

    def to_dict(self) -> dict:
        return {
            "site_dir": str(self.site_dir),
            "out_dir": str(self.out_dir),
            "targets_requested": list(self.targets_requested),
            "preflight": self.preflight.to_dict(),
            "bundles": [b.to_dict() for b in self.bundles],
            "manifest_path": str(self.manifest_path) if self.manifest_path else None,
            "checksums_path": str(self.checksums_path) if self.checksums_path else None,
            "aborted_reason": self.aborted_reason,
            "rebuilt": self.rebuilt,
            "ok": self.ok,
        }


# ── helpers ────────────────────────────────────────────────────


def _normalize_targets(raw: Sequence[str] | None) -> list[str]:
    if not raw:
        return list(DEFAULT_TARGETS)
    expanded: list[str] = []
    for item in raw:
        if item == "all":
            expanded.extend(DEFAULT_TARGETS)
            continue
        if item not in KNOWN_TARGETS:
            raise ValueError(
                f"unknown target {item!r}; expected one of "
                f"{KNOWN_TARGETS + ('all',)!r}"
            )
        expanded.append(item)
    # de-dup, keep first-seen order
    seen: set[str] = set()
    deduped: list[str] = []
    for t in expanded:
        if t in seen:
            continue
        seen.add(t)
        deduped.append(t)
    return deduped


def _iter_site_files(site_dir: Path) -> list[Path]:
    """Return sorted list of files under ``site_dir`` (relative paths)."""
    files = [p for p in site_dir.rglob("*") if p.is_file()]
    files.sort(key=lambda p: p.relative_to(site_dir).as_posix())
    return files


def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _atomic_replace(tmp_path: Path, final_path: Path) -> None:
    final_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path.replace(final_path)


def _cleanup_bundle_paths(archive_path: Path) -> None:
    archive_path.unlink(missing_ok=True)
    archive_path.with_name(archive_path.name + ".tmp").unlink(missing_ok=True)


def _build_zip_bundle(
    target: str,
    site_dir: Path,
    archive_path: Path,
) -> BundleArtifact:
    """Build a deterministic zip archive of ``site_dir``.

    Entries are stored at the top level (i.e. ``index.html`` not
    ``site/index.html``) so Cloudflare Pages Direct Upload sees them as the
    publish root.
    """
    files = _iter_site_files(site_dir)
    tmp_path = archive_path.with_name(archive_path.name + ".tmp")
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    if tmp_path.exists():
        tmp_path.unlink()

    total_uncompressed = 0
    try:
        with zipfile.ZipFile(
            tmp_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
        ) as zf:
            for path in files:
                rel = path.relative_to(site_dir).as_posix()
                data = path.read_bytes()
                total_uncompressed += len(data)
                info = zipfile.ZipInfo(filename=rel, date_time=_ZIP_FIXED_DATE)
                info.compress_type = zipfile.ZIP_DEFLATED
                # Force unix-ish external attrs (rw-r--r-- file).
                info.external_attr = (0o100644 & 0xFFFF) << 16
                info.create_system = 3  # unix
                zf.writestr(info, data)

        _atomic_replace(tmp_path, archive_path)
    except Exception:
        _cleanup_bundle_paths(archive_path)
        raise
    sha = _sha256_of_file(archive_path)
    return BundleArtifact(
        target=target,
        archive_path=archive_path,
        archive_relpath=archive_path.name,
        file_count=len(files),
        total_uncompressed_bytes=total_uncompressed,
        sha256=sha,
    )


def _build_targz_bundle(
    target: str,
    site_dir: Path,
    archive_path: Path,
) -> BundleArtifact:
    """Build a deterministic tar.gz archive of ``site_dir``.

    Entries are stored at the top level. Gzip header carries no timestamp and
    no original filename so byte-identical site contents produce byte-identical
    archive bytes across re-runs.
    """
    files = _iter_site_files(site_dir)
    tmp_path = archive_path.with_name(archive_path.name + ".tmp")
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    if tmp_path.exists():
        tmp_path.unlink()

    # Build the uncompressed tar in memory first so we can wrap it in a gzip
    # stream that has no header timestamp/filename.
    tar_buf = io.BytesIO()
    total_uncompressed = 0
    with tarfile.open(fileobj=tar_buf, mode="w", format=tarfile.USTAR_FORMAT) as tf:
        for path in files:
            rel = path.relative_to(site_dir).as_posix()
            data = path.read_bytes()
            total_uncompressed += len(data)
            info = tarfile.TarInfo(name=rel)
            info.size = len(data)
            info.mtime = _TAR_FIXED_MTIME
            info.mode = 0o644
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            info.type = tarfile.REGTYPE
            tf.addfile(info, io.BytesIO(data))

    import gzip as _gzip

    raw_tar = tar_buf.getvalue()
    try:
        with open(tmp_path, "wb") as out:
            with _gzip.GzipFile(
                filename="",
                mode="wb",
                fileobj=out,
                mtime=0,
                compresslevel=6,
            ) as gz:
                gz.write(raw_tar)

        _atomic_replace(tmp_path, archive_path)
    except Exception:
        _cleanup_bundle_paths(archive_path)
        raise
    sha = _sha256_of_file(archive_path)
    return BundleArtifact(
        target=target,
        archive_path=archive_path,
        archive_relpath=archive_path.name,
        file_count=len(files),
        total_uncompressed_bytes=total_uncompressed,
        sha256=sha,
    )


def _scan_archive_for_cookies(archive_path: Path, target: str) -> list[str]:
    """Open the archive and grep every entry for ``NID_AUT`` / ``NID_SES``.

    Defense in depth: preflight already scanned ``site/``, but we re-scan the
    actual bytes that will leave the machine.
    """
    leaks: list[str] = []
    if target == "cloudflare":
        with zipfile.ZipFile(archive_path, "r") as zf:
            for name in zf.namelist():
                try:
                    data = zf.read(name)
                except (KeyError, RuntimeError):
                    continue
                text = data.decode("utf-8", errors="replace")
                for pat in COOKIE_PATTERNS:
                    if pat.search(text):
                        leaks.append(name)
                        break
    elif target == "github-pages":
        with tarfile.open(archive_path, "r:gz") as tf:
            for member in tf.getmembers():
                if not member.isreg():
                    continue
                fobj = tf.extractfile(member)
                if fobj is None:
                    continue
                data = fobj.read()
                text = data.decode("utf-8", errors="replace")
                for pat in COOKIE_PATTERNS:
                    if pat.search(text):
                        leaks.append(member.name)
                        break
    return leaks


def _maybe_rebuild_site(site_dir: Path) -> bool:
    """Invoke ``publish.builder.build_site`` against the project root.

    Used by ``--rebuild``. We shell out so that a builder failure does not
    half-mutate this process. Returns True on success.
    """
    project_root = Path(__file__).resolve().parent.parent.parent
    cmd = [
        sys.executable,
        "-m",
        "publish.builder.build_site",
        "--site-dir",
        str(site_dir),
    ]
    res = subprocess.run(
        cmd,
        cwd=str(project_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if res.returncode != 0:
        return False
    return True


def _write_manifest(out_dir: Path, result: PackageResult) -> Path:
    manifest = {
        "site_dir": str(result.site_dir),
        "out_dir": str(result.out_dir),
        "targets": [b.target for b in result.bundles],
        "preflight": result.preflight.to_dict(),
        "bundles": [b.to_dict() for b in result.bundles],
        "rebuilt": result.rebuilt,
    }
    path = out_dir / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2, sort_keys=True)
    tmp.replace(path)
    return path


def _write_checksums(out_dir: Path, bundles: Iterable[BundleArtifact]) -> Path:
    path = out_dir / "checksums.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for b in sorted(bundles, key=lambda x: x.target):
        rel = b.archive_path.relative_to(out_dir).as_posix()
        lines.append(f"{b.sha256}  {rel}")
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    tmp.replace(path)
    return path


# ── main entry ────────────────────────────────────────────────


def package(
    site_dir: Path,
    out_dir: Path,
    targets: Sequence[str] | None = None,
    *,
    strict: bool = False,
    rebuild: bool = False,
) -> PackageResult:
    """Run preflight then build deploy bundles for each requested target."""
    site_dir = site_dir.resolve()
    out_dir = out_dir.resolve()
    targets_norm = _normalize_targets(targets)

    rebuilt = False
    if rebuild:
        rebuilt = _maybe_rebuild_site(site_dir)

    pre = preflight(site_dir)
    result = PackageResult(
        site_dir=site_dir,
        out_dir=out_dir,
        targets_requested=targets_norm,
        preflight=pre,
        rebuilt=rebuilt,
    )

    if rebuild and not rebuilt:
        result.aborted_reason = "rebuild requested but builder failed; aborting"
        return result

    if pre.errors:
        result.aborted_reason = (
            f"preflight errors ({len(pre.errors)}); refusing to build deploy bundles"
        )
        return result
    if strict and pre.warnings:
        result.aborted_reason = (
            f"preflight warnings ({len(pre.warnings)}) under --strict; "
            "refusing to build deploy bundles"
        )
        return result

    builders = {
        "cloudflare": _build_zip_bundle,
        "github-pages": _build_targz_bundle,
    }

    for target in targets_norm:
        archive_name = _BUNDLE_FILENAMES[target]
        archive_path = out_dir / target / archive_name
        # remove any prior archive so we never silently keep a stale one
        if archive_path.exists():
            archive_path.unlink()
        try:
            artifact = builders[target](target, site_dir, archive_path)
        except Exception as e:
            _cleanup_bundle_paths(archive_path)
            result.aborted_reason = (
                f"{target} bundle build failed: {type(e).__name__}: {e}"
            )
            return result
        cookie_hits = _scan_archive_for_cookies(archive_path, target)
        if cookie_hits:
            _cleanup_bundle_paths(archive_path)
            result.aborted_reason = (
                f"COOKIE LEAK in built {target} bundle: {cookie_hits}; archive removed"
            )
            return result
        result.bundles.append(artifact)

    result.manifest_path = _write_manifest(out_dir, result)
    result.checksums_path = _write_checksums(out_dir, result.bundles)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Build deploy bundles for the static site.")
    parser.add_argument(
        "--site-dir",
        default="./site",
        help="Path to the built site directory (default: ./site).",
    )
    parser.add_argument(
        "--out-dir",
        default=str(DEFAULT_OUT_DIR),
        help="Directory to write bundles into (default: ./dist/deploy).",
    )
    parser.add_argument(
        "--target",
        action="append",
        choices=list(KNOWN_TARGETS) + ["all"],
        help=(
            "Target to package for. Repeatable. 'all' expands to every known "
            "target. Default: all."
        ),
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat preflight warnings as blocking failures.",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Run publish.builder.build_site against --site-dir before packaging.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove existing --out-dir before writing new bundles.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of human text.",
    )
    args = parser.parse_args()

    site_dir = Path(args.site_dir).resolve()
    out_dir = Path(args.out_dir).resolve()
    if args.clean and out_dir.exists():
        shutil.rmtree(out_dir)

    try:
        result = package(
            site_dir=site_dir,
            out_dir=out_dir,
            targets=args.target,
            strict=args.strict,
            rebuild=args.rebuild,
        )
    except ValueError as e:
        _emit_line(f"argument error: {e}")
        return 2

    if args.json:
        _emit_line(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        _emit_line(f"Package run on: {result.site_dir}")
        _emit_line(f"  out_dir:           {result.out_dir}")
        _emit_line(f"  targets requested: {result.targets_requested}")
        _emit_line(
            f"  preflight:         errors={len(result.preflight.errors)} "
            f"warnings={len(result.preflight.warnings)}"
        )
        if result.aborted_reason:
            _emit_line(f"ABORT: {result.aborted_reason}")
        else:
            for b in result.bundles:
                _emit_line(
                    f"  bundle: {b.target:14s} {b.archive_path.name:24s} "
                    f"files={b.file_count:4d} bytes={b.total_uncompressed_bytes:8d} "
                    f"sha256={b.sha256[:16]}..."
                )
            if result.manifest_path:
                _emit_line(f"  manifest:  {result.manifest_path}")
            if result.checksums_path:
                _emit_line(f"  checksums: {result.checksums_path}")
            _emit_line("OK - deploy bundles ready.")

    if result.aborted_reason:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
