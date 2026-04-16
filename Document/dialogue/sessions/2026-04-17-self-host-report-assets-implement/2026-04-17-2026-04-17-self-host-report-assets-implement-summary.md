# Session Summary: 2026-04-17-self-host-report-assets-implement

## Goal

Close the last blocker between the deploy bundle command (session
2026-04-16-deploy-bundle-command-implement) and running --strict as the
baseline. The packager accepted --strict since Turn 1 of the previous
session, but a single recurring warning -- per-VOD report HTML loading
chart.js + Google Fonts from external CDNs -- forced every CI invocation
to drop back to the non-strict default. This session removes that last
external dependency: chart.js is vendored under publish/web/assets/vendor/,
Google Fonts is replaced with a robust system-font fallback stack, the
summarizer template emits the local chart path, the builder copies the
vendor file into site/ and rewrites legacy output/<base>.html references
on copy, and the preflight scanner learns to ignore the vendored payload's
inert documentation URLs so it does not re-break itself. Result: both
publish.deploy.check --strict and publish.deploy.package --strict --target all
PASS (exit 0, warnings 0) on the real built site/.

## Turn 1 (claude-code)

### Implementation

1. **Vendored chart.js** -- new publish/web/assets/vendor/chart.umd.min.js.
   - Copy of chart.js v4.4.2 minified UMD bundle (205,488 bytes,
     sha256 08dfa4730571b23810c34fc39c5101461ecafca56c3f92caf4850509cb158f30)
     taken verbatim from cdn.jsdelivr.net.
   - Committed under publish/web/ so the builder's existing
     _copy_web_assets() routine materializes it into site/ without a
     separate packaging step.

2. **Template patch** -- pipeline/summarizer.py _generate_html():
   - Replaced the chart.js CDN script tag with a local relative reference
     ../../assets/vendor/chart.umd.min.js. The relative path is fixed
     because report.html always lands at site/vods/<video_no>/report.html.
   - Removed the @import url() line for fonts.googleapis.com. In its
     place, a comment explains the self-host stance.
   - Body font-family now prefers Noto Sans KR but falls through
     Apple SD Gothic Neo, Malgun Gothic, system-ui, -apple-system,
     Segoe UI, sans-serif (Korean-friendly fallback chain). Monospace
     similarly extends 'JetBrains Mono' with Cascadia Code, Fira Code,
     Consolas, 'Courier New', monospace (8 occurrences updated).
   - grep for https:// or @import in pipeline/summarizer.py = 0 hits.

3. **Builder copy + legacy rewrite** -- publish/builder/build_site.py:
   - _copy_web_assets() rels tuple gains
     "assets/vendor/chart.umd.min.js" so the site tree gets the local
     chart bundle.
   - Two compiled regexes (_LEGACY_CHARTJS_CDN_RE,
     _LEGACY_GFONTS_IMPORT_RE) plus a _rewrite_legacy_cdn_html(text)
     helper rewrite the old CDN patterns to the local ones.
   - A new _copy_report_html(src, dst) reads the old HTML as UTF-8,
     applies the rewrite, and writes the result. build_site() calls
     this for report.html, leaving .md and .json on the original
     binary-safe shutil.copyfile path.

4. **Preflight scoping** -- publish/deploy/check.py _check_external_cdn():
   - Files under site/assets/vendor/ are excluded from the external
     URL scan. Vendored minified third-party code contains inert
     documentation URLs (chartjs.org, jsdelivr docs, color library
     readme) that are not runtime fetches; flagging them re-breaks
     --strict for no security benefit.
   - The cookie-leak and absolute-path scanners still cover the
     vendor directory -- those checks have different risk profiles.

5. **6-group verifier** -- experiments/self_host_report_assets_verify.py:
   - Re-runs publish.builder.build_site first so the verifier always
     tests the current code path (--skip-rebuild opts out).
   - T1 asserts every site/vods/<id>/report.html has zero external
     https:// references (schema.org / w3.org excluded) and still
     contains the local chart.js script tag.
   - T2 asserts site/assets/vendor/chart.umd.min.js sha256 matches
     the source under publish/web/.
   - T3 runs python -m publish.deploy.check --strict --json and
     requires exit 0 + warnings 0.
   - T4 runs python -m publish.deploy.package --target all --clean
     --strict into a tempdir and requires exit 0 + both bundles
     present on disk.
   - T5 copies the live site/ into a tempdir, spins up
     http.server on a free port, and issues GET requests for
     /index.html, /vod.html, /vods/<id>/report.html, and
     /assets/vendor/chart.umd.min.js; all four must return 200.
   - T6 greps the whole site/ tree for NID_AUT / NID_SES.
   - T4 and T5 use tempfile.TemporaryDirectory so neither
     dist/deploy/ nor site/ is polluted across runs.

6. **Doc sync**:
   - README.md deploy section adds the self-host note + bumps the
     preflight and package example commands to --strict.
   - docs/deploy-free-hosting.md preflight item restates external CDN
     as "warning only, but this repo is strict-clean because vendor/
     is self-hosted and excluded from the scan"; the reproducible
     verification section documents the new 6-group script.
   - docs/multi-streamer-web-publish-backlog.md P5 status becomes
     "scaffold + bundle CLI + self-host done (real account deploy
     manual)" and the body enumerates the new artifacts + residual
     risks (vendored chart.js update policy).

### Verification

- python experiments/self_host_report_assets_verify.py -> 6/6 PASS:
  - T1 report_html_no_cdn: 1 report CDN-free.
  - T2 vendor_asset_deployed: sha256 08dfa4730571b238..., size 205488.
  - T3 strict_preflight_pass: exit 0, warnings 0, errors 0, vods 1.
  - T4 strict_package_pass: cloudflare bundle 93,220 B,
    github-pages bundle 85,386 B.
  - T5 local_serve_smoke: 200 for all 4 endpoints.
  - T6 cookie_grep: 0 NID_AUT/NID_SES across site/.
- python -m publish.deploy.check --site-dir ./site --strict -> exit 0,
  "OK - deploy preflight clean."
- python -m publish.deploy.package --target all --clean --strict ->
  exit 0, "OK - deploy bundles ready." cloudflare sha256
  f3bbe5dcb7e5c24e..., github-pages sha256 6fce439e2e4db7ab...
- python experiments/deploy_package_verify.py --site-dir ./site -> 5/5
  PASS (previous session's contract still holds; no regression from
  the preflight scoping change).
- DAD packet validator (tools/Validate-DadPacket.ps1 -AllSessions) and
  document validator (tools/Validate-Documents.ps1 -IncludeRootGuides
  -IncludeAgentDocs): expected PASS.

### Out of scope / open risks

- Actual Cloudflare or GitHub Pages deployment was not performed. The
  local site serves chart.js correctly from http.server, but the real
  host's MIME-type handling, brotli response, and cache behavior will
  only be exercised at the first real upload.
- chart.js vendoring is manual. A newer patch release of chart.js (for
  a security fix) has to be dropped into publish/web/assets/vendor/ by
  hand, with the sha256 re-measured against the new bytes. Automating
  this -- lockfile-style manifest, CI job that diffs upstream -- is
  left for a later slice.
- Fonts are explicitly not vendored. Environments missing Noto Sans KR
  or JetBrains Mono will fall through to the OS-installed alternatives.
  If design consistency becomes a harder requirement, a follow-up
  slice can woff2-vendor both families with @font-face and local src.
- The preflight's vendor-directory exclusion is path-based
  (assets/vendor/). If the repo adds another vendored bundle elsewhere,
  either the path rule has to move or the allowlist has to generalize.
- _rewrite_legacy_cdn_html only knows two concrete CDN patterns
  (jsdelivr chart.js, googleapis fonts). A different legacy CDN
  reference baked into an old output/ file would sail through and
  trip the preflight again; adding patterns (or just re-running the
  summarizer) is the remedy.

## Turn 2 (codex peer-verify)

### Reproduction

- C1 auth probe: sister stayed on main at d97514e, live stayed
  detached at d97514e, origin/main resolved to
  d97514e49212d10b6ef8403b829f2612651a452c, and the merge-base check
  matched that baseline.
- C2 dependency audit: pipeline/summarizer.py and
  site/vods/11688000/report.html both re-scanned with zero
  https:// / @import hits. publish/builder/build_site.py still
  includes assets/vendor/chart.umd.min.js in _copy_web_assets(),
  defines _rewrite_legacy_cdn_html() and _copy_report_html(), and
  uses _copy_report_html() inside build_site().
- C3 adversarial probes:
  publish/web/assets/vendor/chart.umd.min.js re-hashed to
  08dfa4730571b23810c34fc39c5101461ecafca56c3f92caf4850509cb158f30
  at 205488 bytes; a fresh python -m publish.builder.build_site
  kept only ../../assets/vendor/chart.umd.min.js; a poisoned legacy
  output/<base>.html copy had both the old jsdelivr chart tag and old
  Google Fonts @import stripped during the temp build; the vendor
  probe (site/assets/vendor/_probe.js) passed strict with exit 0
  and zero warnings, while the top-level probe (site/assets/_top_probe.js)
  failed strict with exit 2 and the expected external URL warning;
  a vendor cookie probe containing NID_AUT failed preflight with exit
  1 and COOKIE LEAK pointing at assets/vendor/_probe.js.
- C4 strict deploy:
  python -m publish.deploy.check --site-dir ./site --strict exited
  0; python -m publish.deploy.package --target all --clean --strict
  exited 0, emitted both bundles plus manifest.json and
  checksums.txt, and both extracted archives had zero NID_AUT /
  NID_SES hits. Repackaging into two temp out-dirs produced identical
  sha256 values for both bundles.
- C5 verification + validators:
  experiments/self_host_report_assets_verify.py returned 6/6 PASS,
  experiments/deploy_package_verify.py --site-dir ./site returned
  5/5 PASS, an independent temp-copy http.server smoke got 200
  from /index.html, /vod.html, /vods/11688000/report.html, and
  /assets/vendor/chart.umd.min.js, and both
  tools/Validate-DadPacket.ps1 -AllSessions plus
  tools/Validate-Documents.ps1 -IncludeRootGuides -IncludeAgentDocs
  passed.

### Outcome

No defects were found during Turn 2. No code or documentation changes
were required beyond recording the peer-verification packet and closing
the session state as converged.

## Verdict

The per-VOD report HTML now loads zero external CDN resources. The
deploy bundle command passes under --strict without any ad-hoc warning
tolerance, closing the last structural blocker between the local
packaging pipeline and a CI that treats --strict as default. The
vendored asset round-trips correctly through a local HTTP server, and
both existing verifier suites stay green.
