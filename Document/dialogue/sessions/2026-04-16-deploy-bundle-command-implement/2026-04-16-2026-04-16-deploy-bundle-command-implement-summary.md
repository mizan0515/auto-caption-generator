# Session Summary: 2026-04-16-deploy-bundle-command-implement
## Goal
Close the gap between the deploy scaffold (session
2026-04-16-free-hosting-deploy-scaffold) and the first upload click. The
scaffold proved the static site/ tree can be served by Cloudflare Pages or
GitHub Pages, but the operator still had to hand-roll an upload bundle for
each platform. This session adds a single command that turns site/ into
upload-ready archives for both targets, with preflight gating, deterministic
output, and a defense-in-depth cookie scan over the produced archives.
Real account-bound deployment is still out of scope.
## Turn 1 (claude-code)
### Implementation
1. **Bundle CLI/library** -- new publish/deploy/package.py.
   - Targets cloudflare and github-pages. The literal all expands to
     both.
   - Library entry: package(site_dir, out_dir, targets, *, strict, rebuild)
     returns a PackageResult with the run preflight, the per-target
     BundleArtifact list, manifest and checksums paths, and an
     aborted_reason field.
   - Preflight gating: the run calls
     publish.deploy.check.preflight() first. Any error aborts and writes no
     archive. Under --strict any warning aborts the same way.
   - Cloudflare bundle is a deflate zip with ZipInfo.date_time fixed to
     1980-01-01 (zip cannot represent epoch 0), unix 0644 external attrs,
     and entries stored at the publish root.
   - GitHub Pages bundle is a USTAR tar wrapped in a gzip stream with
     mtime=0 and an empty filename header. Each TarInfo carries
     mtime=315532800, uid=gid=0, empty owner and group names, mode
     0644. Entries are stored at the publish root.
   - All archives are written through *.tmp and eplace-d into place so
     interrupted runs never leave partial files behind.
   - Defense in depth: every archive is reopened and every entry is
     re-scanned against publish.deploy.check.COOKIE_PATTERNS. A hit deletes
     the archive and aborts with COOKIE LEAK in built ... bundle.
   - CLI flags: --site-dir, --out-dir, --target (repeatable, including
     the all alias), --strict, --rebuild, --clean, --json. Human
     output is routed through the console-safe writer added to
     publish.deploy.check so cp949 consoles do not crash.
   - Output layout under dist/deploy/ (already gitignored): per-target
     archive plus a manifest JSON file (sorted keys, archive metadata +
     preflight snapshot) and a checksums text file (one sha256  relpath
     line per bundle, LF-terminated, target-sorted).
2. **Package docstring sync** -- publish/deploy/__init__.py now lists the
   new publish.deploy.package entry alongside publish.deploy.check.
3. **Reproducible 5-group verifier** -- new
   experiments/deploy_package_verify.py:
   - T1+T2+T3 builds real bundles against the live site/ tree, asserts the
     expected publish-root entries are present in both archives, asserts no
     entry sits under a site/ prefix, and asserts the archives have a
     single deterministic date_time / mtime value plus zero ownership.
     Manifest and checksums file format is also checked.
   - T4 poisons a copied search-index.json with both a plain NID_AUT
     token and an escaped JSON-string NID_SES token. The packager must
     abort with no archive on disk.
   - T5 deletes _headers from a copy of site/. The non-strict run still
     produces a bundle; the --strict run aborts with no archive on disk.
   - T6 packages the same input into two output directories and compares the
     per-target sha256 values; both must match.
   - T7 reopens every archive produced from the live tree and greps every
     entry for NID_AUT and NID_SES. Both must be zero.
   - The whole verifier runs inside a single 	empfile.TemporaryDirectory
     so it does not pollute the working tree.
4. **Doc sync**:
   - README.md deploy section adds the new command as step 3 with all
     flags documented and the resulting layout listed; the Cloudflare
     option A bullet list now mentions the zip upload path.
   - docs/deploy-free-hosting.md adds the bundle command as step 4 of the
     standard flow, lists the four dist/deploy/ outputs in the deploy
     checklist, and points operators at the new verifier under the
     reproducible-verification section.
   - docs/multi-streamer-web-publish-backlog.md P5 status is now
     "scaffold + bundle CLI ?? (? ?? ??? ??)"; the body lists the
     new artifacts (package.py + deploy_package_verify.py) and notes
     that bundle attachment to CI artifacts or GitHub releases is still
     pending.
### Verification
- python experiments/deploy_package_verify.py --site-dir ./site -> 5/5 PASS:
  - T1+T2+T3 real bundles + layout: cloudflare zip 17 entries,
    github-pages tar.gz 17 entries, all deterministic.
  - T4 preflight cookie injection blocks the run, archive missing.
  - T5 missing _headers warns under non-strict but blocks under
    --strict.
  - T6 sha256 identical across two runs (cloudflare 0aad8fb92554...,
    github-pages 0574f7d507b1...).
  - T7 zero cookie hits across both archives.
- python -m publish.deploy.package --target all --clean against the real
  site/ produces the expected
  dist/deploy/{cloudflare/site-upload.zip, github-pages/site-artifact.tar.gz,
  manifest.json, checksums.txt} artifacts; the per-bundle sha256 matches
  the verifier observation, confirming determinism between the two code
  paths.
- The packager run reuses the previous session's preflight output: errors
  zero, warnings one (the existing external CDN reference inside
  per-VOD report HTML for chart.js and Google Fonts).
- DAD packet validator (tools/Validate-DadPacket.ps1 with -AllSessions) and
  document validator (tools/Validate-Documents.ps1 with -IncludeRootGuides
  and -IncludeAgentDocs): PASS.
### Out of scope / open risks
- Real Cloudflare or GitHub Pages account push was not executed. The
  archive layout, format, and reproducibility are simulated locally only;
  the actual platform response (upload accepted, site live, headers
  applied) remains a manual trigger.
- The packager does not change the existing external CDN warning in the
  preflight output. Turning on --strict in CI therefore requires first
  closing the per-VOD report HTML CDN dependency (a separate slice on the
  P5 backlog).
- The manifest JSON records absolute paths under the runtime working
  tree. Moving the bundle around invalidates the archive_path field;
  downstream consumers must rely on archive_relpath.
- The deterministic 1980-01-01 epoch was chosen because zip cannot
  represent earlier dates. If GitHub's upload-pages-artifact action
  uses entry mtime as a cache key, this fixed value could weaken cache
  busting; behavior in the real action will need to be observed once
  someone runs the workflow.
- Cookie scanning still only covers decoded text payloads. Binary or
  obfuscated leaks (image steganography, base64 fragments) are out of
  reach. This remains a first-line defense, not a full secret scanner.
## Turn 2 (codex peer-verify)
Codex re-ran C1-C5 directly and found two concrete defects.
1. **Escaped JSON cookie leak bypass**
   - publish.deploy.check.COOKIE_PATTERNS used word-boundary regexes.
   - An injected text payload like "line1\\nNID_SES\\nline2" inside
     search-index.json bypassed both preflight and archive rescans, so the
     package command still wrote deploy bundles.
   - Fix: cookie detection now treats NID_AUT and NID_SES as toxic
     substrings anywhere in decoded text payloads.
2. **Atomic tmp cleanup gap**
   - If a bundle builder raised after creating site-upload.zip.tmp, the
     exception propagated and the temp archive remained on disk.
   - Fix: publish.deploy.package now cleans both the final archive path and
     its *.tmp sibling on builder failure and on post-build cookie-hit aborts.
### Turn 2 re-verification
- C1 auth probe: PASS
- C2 deploy-flow audit: PASS
- C3 bundle CLI implementation: PASS
- C4 deploy safety: FAIL-then-FIXED
- C5 verification + validators: FAIL-then-FIXED
Additional adversarial checks after the fixes:
- escaped NID_SES injection into a copied site/search-index.json now
  yields EXIT 1 and ARCHIVE_COUNT 0
- monkeypatched builder failure now yields
  TMP_EXISTS False, FINAL_EXISTS False
- experiments/deploy_package_verify.py still passes 5/5 after the fixes
- real python -m publish.deploy.package --target all --clean still produces
  the same deterministic bundle hashes
- manifest.json is byte-identical across repeat runs
- tools/Validate-DadPacket.ps1: PASS
- tools/Validate-Documents.ps1: PASS
## Verdict
The deploy bundle command now closes the site/ -> upload handoff honestly.
It packages deterministic Cloudflare and GitHub Pages bundles, blocks cookie
leaks in both plain and escaped-text forms, cleans temp artifacts on builder
failure, and remains locally reproducible without touching a real hosting
account. Follow-up slices remain the same: one real hosted upload round-trip,
CI artifact/release attachment, and removal or self-hosting of the per-VOD
report HTML external CDN dependency.