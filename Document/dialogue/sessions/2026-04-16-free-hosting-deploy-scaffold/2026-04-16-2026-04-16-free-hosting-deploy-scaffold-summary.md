# Session Summary: 2026-04-16-free-hosting-deploy-scaffold

## Goal

Build a deploy-ready scaffold so the existing `site/` static tree can be
published to a free static host without ad-hoc setup. Cloudflare Pages is the
primary target; GitHub Pages is a manual-trigger fallback. Real account-bound
deployment is out of scope; the deliverable is "everything below the first
deploy click is in place and locally verifiable."

## Turn 1 (claude-code)

### Implementation

1. **Builder emits deploy meta**
   - New `publish/web/_redirects` (Cloudflare 404 fallback).
   - New `publish/web/_headers` (assets 1d / HTML+JSON 5m, `nosniff`,
     Referrer-Policy strict-origin-when-cross-origin,
     X-Frame-Options SAMEORIGIN to keep the VOD shell page iframing
     the per-VOD report body, Permissions-Policy disabling geo/mic/cam).
   - New `publish/web/.nojekyll` (GitHub Pages compatibility).
   - The `_copy_web_assets()` helper inside `publish/builder/build_site.py`
     was extended to copy these three files into `site/` on every build.

2. **Cloudflare Pages control plane**
   - `wrangler.toml` at repo root (`name`, `compatibility_date`,
     `pages_build_output_dir = ./site`) supports both Direct Upload and
     Wrangler CLI flows.

3. **GitHub Pages fallback**
   - New workflow file `.github/workflows/deploy-pages.yml`, manual
     `workflow_dispatch` only.
   - Verifies `site/index.html`, ensures `.nojekyll`, runs an inline
     grep cookie gate for NID_AUT and NID_SES, then uses
     configure-pages v5, upload-pages-artifact v3, and deploy-pages v4.
   - Header comment documents three operating paths because `site/` is
     gitignored in this repo.

4. **Preflight CLI/library**
   - New package files `publish/deploy/__init__.py` and
     `publish/deploy/check.py` with a `preflight()` library entry plus a
     CLI:
     - Required HTML, JSON, and asset structure.
     - Index counts (>= 1 streamer, >= 1 VOD).
     - Cookie leak scan (NID_AUT, NID_SES) -> ERROR.
     - Absolute path leakage -> WARNING.
     - External CDN reference -> WARNING.
     - `--strict` (warnings -> exit 2), `--json` machine output.

5. **Reproducible 8-test verifier**
   - New script `experiments/deploy_scaffold_verify.py` covering:
     T1 build emits the three deploy meta files,
     T2 preflight clean,
     T3 NID_AUT injection caught as ERROR,
     T4 missing `_headers` -> WARNING + `--strict` non-zero,
     T5 `wrangler.toml` parses with the required Pages keys,
     T6 the GitHub Pages workflow parses, is `workflow_dispatch`-only,
        and references upload-pages-artifact v3 + deploy-pages v4 plus
        the cookie gate strings,
     T7 a Python http.server against the built site returns 200 for
        the index.html and index.json URLs,
     T8 the real built tree contains zero NID_AUT or NID_SES.

6. **Doc sync**
   - `README.md` deploy section rewritten (preflight + Direct Upload +
     Wrangler CLI + GitHub Pages workflow + gitignored `site/` caveat).
   - `docs/deploy-free-hosting.md` rewritten with the standard
     build -> preflight -> serve -> deploy flow, both Cloudflare options,
     GitHub Pages workflow internals, deploy checklist, and verifier
     reference.
   - `docs/multi-streamer-web-publish-backlog.md` P5 status updated to
     "scaffold 완료 (실 계정 배포는 수동)" with new artifact and
     deferred lists.

### Verification

- 8-test verifier: 8/8 PASS.
- Builder run reports `vod_count: 1, streamer_count: 1, assets_copied: 9`
  (deploy meta included).
- Preflight on the real built site: OK with one warning (external CDN
  reference inside the per-VOD report HTML for chart.js + Google
  Fonts; pre-existing runtime report dependency, out of scope).
- Recursive grep for NID_AUT or NID_SES under the built site: 0 hits.
- DAD packet validator (tools/Validate-DadPacket.ps1 with -AllSessions) and
  document validator
  (tools/Validate-Documents.ps1 with -IncludeRootGuides -IncludeAgentDocs):
  expected PASS after this rewrite.

### Out of scope / open risks

- No real Cloudflare or GitHub Pages account was touched. The scaffold is
  proven by local simulation (build, preflight, HTTP serve, parse) only.
- Per-VOD report HTML files reference chart.js and Google Fonts via
  HTTPS. Cloudflare and GitHub Pages both allow that, but offline or
  CSP-tight environments would break. Self-host or CSP decision is a
  future slice.
- Because `site/` is gitignored, the GitHub Pages workflow does not run
  in CI out-of-the-box. Operator must commit to a publish branch,
  un-ignore `site/`, or wire an artifact download step from another
  workflow.
- Cookie leak gate uses word-boundary NID_AUT / NID_SES patterns.
  Obfuscated variants are not caught; this is a first-line defense, not
  a full secret scanner.

## Verdict

Free hosting deploy scaffold is in place and locally verified. Real
account-bound deployment, incremental builds, and report-HTML CDN
self-hosting are explicit follow-up slices.

## Turn 2 (codex peer-verify)

Codex re-ran C1-C5 directly instead of trusting the Turn 1 closeout and found
two concrete defects:

1. The deploy preflight CLI crashed on a default Windows cp949 console when it
   tried to print the external-CDN warning.
2. The site builder was not idempotent because the generated_at field in the
   top-level site index used the current wall-clock time.

Both were fixed inline:

- The deploy preflight module now emits output through a console-safe writer so
  warnings no longer crash the CLI on narrow Windows encodings.
- The site builder now derives generated_at deterministically from the input
  records instead of using a fresh runtime timestamp.

Turn 2 re-verification after the fixes:

- C1 auth probe: PASS
- C2 Cloudflare scaffold: PASS
- C3 GitHub Pages fallback: PASS
- C4 deploy safety: FAIL-then-FIXED
- C5 verification + validators: FAIL-then-FIXED

Additional adversarial checks that now pass:

- deleting `site/` and rebuilding still emits `_redirects`, `_headers`,
  `.nojekyll`
- workflow-style grep gate with injected `NID_AUT` fails closed
- preflight detects injected `NID_SES` as an ERROR
- `--strict` returns exit code `2` on warnings-only site trees
- repeated verifier runs stay clean
- repeated `build_site` runs keep key JSON hashes stable

Final state after Turn 2:

- session/root state sealed as `converged`
- tools/Validate-DadPacket.ps1: PASS
- tools/Validate-Documents.ps1: PASS
