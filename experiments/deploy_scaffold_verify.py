"""End-to-end deploy scaffold verification.

Tests:
  T1. build_site() emits the deploy meta files (_redirects, _headers, .nojekyll)
      into the site root.
  T2. publish.deploy.check.preflight() PASSes on a fresh build with no cookie
      leaks, no missing required files, populated index counts.
  T3. preflight() detects an injected NID_AUT/NID_SES leak as an ERROR.
  T4. preflight() in --strict mode detects a missing _headers as a WARNING
      that becomes a non-zero exit.
  T5. wrangler.toml is well-formed TOML with the required Pages keys.
  T6. .github/workflows/deploy-pages.yml is well-formed YAML, manual-trigger only,
      includes a cookie leak preflight step, and references upload-pages-artifact
      v3 + deploy-pages v4.
  T7. Local HTTP serving smoke: spin up python -m http.server against the built
      site and verify index.html / index.json fetch with 200.
  T8. Cookie leak scan against the actually-built site (defense in depth).

Run:
  PYTHONIOENCODING=utf-8 python experiments/deploy_scaffold_verify.py
"""
from __future__ import annotations

import http.client
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _print(msg: str) -> None:
    print(msg, flush=True)


def _ok(name: str, detail: str = "") -> None:
    if detail:
        _print(f"[PASS] {name} -- {detail}")
    else:
        _print(f"[PASS] {name}")


def _fail(name: str, detail: str) -> None:
    _print(f"[FAIL] {name} -- {detail}")


def _build_into(tmp: Path) -> dict:
    """Build site/ from real ./output into a temp directory and return result."""
    from publish.builder.build_site import build_site

    return build_site(
        output_dir=ROOT / "output",
        site_dir=tmp,
        project_root=ROOT,
    )


def t1_build_emits_deploy_meta(site: Path) -> bool:
    expected = ("_redirects", "_headers", ".nojekyll")
    missing = [name for name in expected if not (site / name).exists()]
    if missing:
        _fail("T1 build_emits_deploy_meta", f"missing in built site: {missing}")
        return False
    # Sanity: _redirects has the 404 fallback; _headers has at least one block.
    redirects_text = (site / "_redirects").read_text(encoding="utf-8")
    if "/index.html" not in redirects_text or "404" not in redirects_text:
        _fail("T1 build_emits_deploy_meta", f"_redirects missing 404 fallback rule:\n{redirects_text!r}")
        return False
    headers_text = (site / "_headers").read_text(encoding="utf-8")
    if "Cache-Control" not in headers_text or "/assets/*" not in headers_text:
        _fail("T1 build_emits_deploy_meta", "_headers missing Cache-Control/assets rule")
        return False
    _ok("T1 build_emits_deploy_meta", "all three meta files present and non-trivial")
    return True


def t2_preflight_clean(site: Path) -> bool:
    from publish.deploy.check import preflight

    result = preflight(site)
    if not result.ok:
        _fail("T2 preflight_clean", f"errors: {result.errors}")
        return False
    if result.info.get("total_vods", 0) < 1:
        _fail("T2 preflight_clean", f"index reports zero vods: {result.info}")
        return False
    if result.info.get("total_streamers", 0) < 1:
        _fail("T2 preflight_clean", f"index reports zero streamers: {result.info}")
        return False
    _ok(
        "T2 preflight_clean",
        f"streamers={result.info['total_streamers']} vods={result.info['total_vods']} "
        f"warnings={len(result.warnings)}",
    )
    return True


def t3_preflight_detects_cookie_leak(site_template: Path) -> bool:
    """Copy a clean built site into a tmpdir, inject NID_AUT into a JSON file,
    and verify preflight() flags it as an ERROR."""
    from publish.deploy.check import preflight

    with tempfile.TemporaryDirectory() as tmp:
        tmp_site = Path(tmp) / "site"
        shutil.copytree(site_template, tmp_site)
        # Inject NID_AUT into search-index.json (the most likely realistic source)
        si = tmp_site / "search-index.json"
        rows = json.loads(si.read_text(encoding="utf-8"))
        if not rows:
            _fail("T3 cookie_leak_detection", "search-index.json empty — cannot inject")
            return False
        rows[0]["search_text"] = (rows[0].get("search_text") or "") + " NID_AUT=secrettoken"
        si.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

        result = preflight(tmp_site)
        if result.ok:
            _fail(
                "T3 cookie_leak_detection",
                f"injected NID_AUT not detected; errors={result.errors} warnings={result.warnings}",
            )
            return False
        if not any("COOKIE LEAK" in e for e in result.errors):
            _fail("T3 cookie_leak_detection", f"errors do not name COOKIE LEAK: {result.errors}")
            return False
    _ok("T3 cookie_leak_detection", "NID_AUT injection caught and reported as ERROR")
    return True


def t4_preflight_strict_mode(site_template: Path) -> bool:
    """Remove _headers from a copy and confirm preflight warns + --strict fails."""
    from publish.deploy.check import preflight

    with tempfile.TemporaryDirectory() as tmp:
        tmp_site = Path(tmp) / "site"
        shutil.copytree(site_template, tmp_site)
        (tmp_site / "_headers").unlink()

        result = preflight(tmp_site)
        if not result.ok:
            _fail("T4 strict_mode", f"non-strict should still pass; errors={result.errors}")
            return False
        if not any("Cloudflare deploy meta" in w for w in result.warnings):
            _fail("T4 strict_mode", f"warning for missing Cloudflare meta not raised: {result.warnings}")
            return False

        # Now run via CLI in --strict and assert non-zero exit.
        # Force UTF-8 decoding so non-ASCII CLI output (e.g. unicode arrows) does
        # not trip Windows' cp949 default and spam an unrelated decode traceback.
        cli = subprocess.run(
            [sys.executable, "-m", "publish.deploy.check", "--site-dir", str(tmp_site), "--strict"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if cli.returncode == 0:
            _fail("T4 strict_mode", f"--strict should fail with warnings; got rc={cli.returncode}\n{cli.stdout}")
            return False
    _ok("T4 strict_mode", "warning surfaced and --strict yields non-zero exit")
    return True


def t5_wrangler_toml() -> bool:
    path = ROOT / "wrangler.toml"
    if not path.is_file():
        _fail("T5 wrangler_toml", "wrangler.toml not found at repo root")
        return False
    text = path.read_text(encoding="utf-8")
    # Light TOML parse via tomllib (Python 3.11+). Fall back to manual key check.
    try:
        import tomllib  # type: ignore[attr-defined]
        cfg = tomllib.loads(text)
    except Exception as e:
        _fail("T5 wrangler_toml", f"tomllib failed to parse: {e}")
        return False
    required_keys = ("name", "compatibility_date", "pages_build_output_dir")
    missing = [k for k in required_keys if k not in cfg]
    if missing:
        _fail("T5 wrangler_toml", f"missing keys: {missing}; got {list(cfg.keys())}")
        return False
    if cfg["pages_build_output_dir"] not in ("./site", "site"):
        _fail("T5 wrangler_toml", f"pages_build_output_dir must point to site/, got {cfg['pages_build_output_dir']!r}")
        return False
    _ok("T5 wrangler_toml", f"valid TOML with required Pages keys ({cfg['name']})")
    return True


def t6_github_workflow() -> bool:
    path = ROOT / ".github" / "workflows" / "deploy-pages.yml"
    if not path.is_file():
        _fail("T6 github_workflow", "deploy-pages.yml not found")
        return False
    text = path.read_text(encoding="utf-8")
    # Verify YAML parses
    try:
        try:
            import yaml  # type: ignore
            cfg = yaml.safe_load(text)
        except ImportError:
            cfg = None
    except Exception as e:
        _fail("T6 github_workflow", f"YAML parse error: {e}")
        return False

    if cfg is not None:
        # Note: PyYAML maps the YAML key `on:` (truthy boolean) to Python True.
        # Accept either string "on" or boolean True as the trigger key.
        triggers = cfg.get("on")
        if triggers is None:
            triggers = cfg.get(True)
        if not triggers or "workflow_dispatch" not in (triggers if isinstance(triggers, dict) else {}):
            _fail("T6 github_workflow", f"on: must contain workflow_dispatch only; got {triggers!r}")
            return False
        if isinstance(triggers, dict) and "push" in triggers:
            _fail("T6 github_workflow", "push trigger present — must be manual only")
            return False
    else:
        # PyYAML missing → use textual checks
        if "workflow_dispatch:" not in text:
            _fail("T6 github_workflow", "workflow_dispatch trigger missing")
            return False
        if "\non:\n" in text and "  push:" in text:
            _fail("T6 github_workflow", "push trigger present — must be manual only")
            return False

    # Required action references
    required_substrings = (
        "actions/upload-pages-artifact@v3",
        "actions/deploy-pages@v4",
        "NID_AUT",  # cookie preflight string is present
        "site/index.html",
        ".nojekyll",
    )
    missing = [s for s in required_substrings if s not in text]
    if missing:
        _fail("T6 github_workflow", f"missing required content: {missing}")
        return False

    _ok("T6 github_workflow", "manual-only, includes cookie preflight + correct action versions")
    return True


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def t7_local_serving(site: Path) -> bool:
    """Spin up python -m http.server and verify static fetch works."""
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--directory", str(site)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        # Wait for the server to come up (up to ~3s).
        deadline = time.monotonic() + 3.0
        ready = False
        while time.monotonic() < deadline:
            try:
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=0.3)
                conn.request("GET", "/index.html")
                resp = conn.getresponse()
                if resp.status == 200:
                    ready = True
                    body = resp.read(2048)
                    conn.close()
                    break
                conn.close()
            except Exception:
                time.sleep(0.1)
        if not ready:
            _fail("T7 local_serving", f"HTTP server on :{port} never returned 200 for /index.html")
            return False
        if b"<title>" not in body:
            _fail("T7 local_serving", "/index.html body lacks <title> tag")
            return False

        # Also confirm /index.json is reachable
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=1.0)
        conn.request("GET", "/index.json")
        resp = conn.getresponse()
        ok_json = resp.status == 200
        body2 = resp.read(2048)
        conn.close()
        if not ok_json:
            _fail("T7 local_serving", f"/index.json returned {resp.status}")
            return False
        try:
            payload = json.loads(body2.decode("utf-8"))
        except json.JSONDecodeError as e:
            _fail("T7 local_serving", f"/index.json not valid JSON: {e}")
            return False
        if "total_vods" not in payload:
            _fail("T7 local_serving", f"/index.json missing total_vods: {list(payload)}")
            return False
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            proc.kill()
    _ok("T7 local_serving", f"served port {port}, /index.html + /index.json both 200")
    return True


def t8_cookie_scan_real_build(site: Path) -> bool:
    """Defense in depth: re-grep the built site once more for cookie tokens."""
    text_suffixes = {".html", ".json", ".js", ".css", ".md", ".txt"}
    leaks: list[str] = []
    for path in site.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in text_suffixes:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "NID_AUT" in text or "NID_SES" in text:
            leaks.append(str(path.relative_to(site)))
    if leaks:
        _fail("T8 cookie_scan_real_build", f"NID_AUT/NID_SES present in: {leaks}")
        return False
    _ok("T8 cookie_scan_real_build", "no cookie tokens in any built text file")
    return True


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        site = Path(tmp) / "site"
        try:
            build_result = _build_into(site)
        except Exception as e:
            _fail("BOOTSTRAP", f"build_site failed: {e}\n{traceback.format_exc()}")
            return 1
        _print(f"[BOOTSTRAP] built {build_result['vod_count']} VOD(s) into {site}")

        tests = [
            ("T1 build_emits_deploy_meta", lambda: t1_build_emits_deploy_meta(site)),
            ("T2 preflight_clean", lambda: t2_preflight_clean(site)),
            ("T3 cookie_leak_detection", lambda: t3_preflight_detects_cookie_leak(site)),
            ("T4 strict_mode", lambda: t4_preflight_strict_mode(site)),
            ("T5 wrangler_toml", lambda: t5_wrangler_toml()),
            ("T6 github_workflow", lambda: t6_github_workflow()),
            ("T7 local_serving", lambda: t7_local_serving(site)),
            ("T8 cookie_scan_real_build", lambda: t8_cookie_scan_real_build(site)),
        ]
        failures = 0
        for name, fn in tests:
            try:
                ok = fn()
            except Exception as e:
                _fail(name, f"unhandled: {e}\n{traceback.format_exc()}")
                ok = False
            if not ok:
                failures += 1

    _print("")
    if failures:
        _print(f"=== {failures} test(s) FAILED ===")
        return 1
    _print(f"=== all {len(tests)} tests PASSED ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
