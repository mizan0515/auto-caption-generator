---
doc_type: dad-session-artifact
session_id: 2026-04-15-a4-closeout-hygiene
artifact: provenance-boundary
turn_origin: 3
revised_in_turn: 5
status: execute-ready
---

# A4 Closeout Hygiene — Provenance Boundary Map (Option B)

Originally drafted in Turn 3, corrected in Turn 5 per Turn 4 peer amendments
A1/A2/A3/A4. Classifies every currently-modified or untracked path into
provenance groups so that the `G3` ACK rubric can be judged against the right
file set, not the whole worktree.

## 0. Baseline (live at Turn 5)

Observed at Turn 5 execute (auth probe: `claude -p "ping"` -> `pong`, 200 OK):

- Branch: codex/local-dirty-preserved  (Turn 2 recorded codex/phase-a1-token-logging)
- HEAD: `c6b0adc "Add DAD artifacts and A1-A4 experiment closeout"`  (Turn 2 recorded `b62ada1`)
- `git status --short` raw line count: **16 modified + 8 untracked** status entries.
  Turn 3 originally wrote "15 modified + 12 untracked" — that is corrected here
  per Turn 4 amendment A1. The divergence had two causes:
  (i) Turn 3 omitted `Document/dialogue/state.json` from the modified list;
  (ii) Turn 3 expanded the hygiene-session directory into its internal files
  instead of treating it as the single collapsed `??` entry git actually prints.
- `git ls-files experiments/ Document/ tools/ | wc -l`: **74**  (Turn 2 recorded 0)
- A4 result artifacts (`experiments/results/2026-04-15_phase-a4_raw.json`,
  `experiments/results/2026-04-15_phase-a4_generalization.md`): first appear in `c6b0adc`.
- A parallel commit `0c078ea "Add DAD artifacts and A1-A4 experiment closeout"` exists
  on another branch; `git diff --stat c6b0adc 0c078ea` = README.md only (1 line).
  `git merge-base c6b0adc 0c078ea` = `b62ada1`, i.e. they are sibling commits off
  the same parent, not an ancestor chain. Turn 5 fixes the canonical choice:
  **`c6b0adc` is canonical for A4 artifact-freeze; `0c078ea` is a README-only
  sibling and is not referenced by anchor or session plans.**

### Drift statement vs Turn 2 C1 baseline

`c6b0adc` is new between Turn 2 and Turn 3 and materially moves the
provenance problem: the DAD scaffolding, session artifacts, A4 result files,
and `experiments/a4_measure.py` are all now tracked. The remaining provenance
gap is *asymmetric* — result artifacts are frozen, measurement-time pipeline
source is not.

### Counting convention (collapsed vs expanded)

Two different counts live in this document and must not be conflated:

- **Status-entry count** = number of lines printed by `git status --short`.
  Modified entries are 16, untracked entries are 8. The hygiene-session
  directory is one collapsed `??` line.
- **Expanded-file count** inside an untracked directory (used only when
  planning which individual files a future commit will stage). The hygiene
  session directory currently expands to 8 files at Turn 5: `state.json`,
  `turn-01.yaml`, `turn-02.yaml`, `turn-03.yaml`, `turn-04.yaml`,
  `turn-05.yaml` (this turn), `provenance-boundary.md`, and `freeze-plan.md`.

G5 before/after snapshots use the status-entry count. Commit-allowlist
planning uses the expanded-file count.

## 1. Grouping rule

Each path is assigned to exactly one group:

- **G-A4-ANCHOR** — measurement-time source that A4 numbers depend on.
  This is the 5-file anchor set from C3: `pipeline/config.py`, `pipeline/main.py`,
  `pipeline/chunker.py`, `pipeline/claude_cli.py`, `pipeline/summarizer.py`.
  G3 must cover these or A4 arithmetic cannot be reproduced from committed source.

- **G-A4-ARTIFACT** — A4 result documents and the execute harness that emitted them.
  `experiments/results/2026-04-15_phase-a4_*.{json,md}`, `experiments/a4_measure.py`,
  `experiments/_a4_*.{json,py}`, and the A4 session YAMLs.
  These are the reproducibility *output side*.

- **G-DAD-SCAFFOLD** — DAD infrastructure shared across A1–A4 and beyond.
  Protocol docs, validators, slash commands, skill files, dialogue state, past-session
  artifacts. Not unique to A4.

- **G-A1..A3-ARTIFACT** — historic experiment artifacts older than A4.
  `experiments/results/2026-04-14_*`, `experiments/results/2026-04-15_phase-a{2,3}_*`,
  `experiments/a3_measure.py`, `experiments/chunk_size_experiment.py`.

- **G-HYGIENE-SESSION** — the current closeout-hygiene session directory only.
  `Document/dialogue/sessions/2026-04-15-a4-closeout-hygiene/**`.

- **G-UNRELATED-DIRTY** — in-flight pipeline work, doc drift, or log/txt output
  that is not on the A4 measurement path and not part of DAD infra.
  `.gitignore`, `README.md`, non-anchor `pipeline/*.py`, `prompts/청크 통합 프롬프트.md`,
  `pipeline/community_matcher.py`, `pipeline/subtitle_analyzer.py`,
  `experiments/_a4_run_*.txt`, `experiments/a3_measure.log`,
  `experiments/parser_test_output.txt`, `experiments/results/run.log`.

## 2. Path inventory (live worktree)

Each row: path · worktree state · covered-by-c6b0adc? · group.
Worktree state is `M` for `git status --short` modified and `?` for untracked.

### 2.1 Modified (16 status entries)

| Path | State | In c6b0adc? | Group |
|---|---|---|---|
| `.gitignore` | M | tracked at HEAD | G-UNRELATED-DIRTY |
| `Document/dialogue/state.json` | M | tracked at HEAD (as A4-converged contents) | **G-HYGIENE-SESSION** |
| `README.md` | M | tracked at HEAD | G-UNRELATED-DIRTY |
| `pipeline/chat_analyzer.py` | M | tracked at HEAD | G-UNRELATED-DIRTY |
| `pipeline/chat_collector.py` | M | tracked at HEAD | G-UNRELATED-DIRTY |
| `pipeline/chunker.py` | M | tracked at HEAD | **G-A4-ANCHOR** |
| `pipeline/claude_cli.py` | M | tracked at HEAD | **G-A4-ANCHOR** |
| `pipeline/config.py` | M | tracked at HEAD | **G-A4-ANCHOR** |
| `pipeline/downloader.py` | M | tracked at HEAD | G-UNRELATED-DIRTY |
| `pipeline/main.py` | M | tracked at HEAD | **G-A4-ANCHOR** |
| `pipeline/monitor.py` | M | tracked at HEAD | G-UNRELATED-DIRTY |
| `pipeline/scraper.py` | M | tracked at HEAD | G-UNRELATED-DIRTY |
| `pipeline/settings_ui.py` | M | tracked at HEAD | G-UNRELATED-DIRTY |
| `pipeline/summarizer.py` | M | tracked at HEAD | **G-A4-ANCHOR** |
| `pipeline/utils.py` | M | tracked at HEAD | G-UNRELATED-DIRTY |
| `prompts/청크 통합 프롬프트.md` | M | tracked at HEAD | G-UNRELATED-DIRTY |

`Document/dialogue/state.json` is grouped G-HYGIENE-SESSION rather than
G-DAD-SCAFFOLD because the current diff against `c6b0adc` is exactly the
hygiene-session turn/decision updates; the file-at-rest in `c6b0adc` still
carries A4-converged contents. That means the file is co-owned by the
hygiene session logically and must travel with the session commit, not with
a separate scaffolding commit.

All 5 anchors are **tracked** at `c6b0adc` but their current working-tree
content is *not* what A4 measured against — they carry the same ~731 insert /
182 delete diff vs `c6b0adc` that Turn 2 recorded against the old HEAD. In
other words, `c6b0adc` captured the pre-A1 anchor state (inherited from
`f4eae41`), not the measurement-time anchor state. **G-A4-ANCHOR is the
remaining G3 gap.**

### 2.2 Untracked (8 status entries; one is a directory)

| Path | In c6b0adc? | Group |
|---|---|---|
| `Document/dialogue/sessions/2026-04-15-a4-closeout-hygiene/` | no (collapsed dir) | G-HYGIENE-SESSION |
| `experiments/_a4_run_1h.txt` | no | G-UNRELATED-DIRTY |
| `experiments/_a4_run_3h.txt` | no | G-UNRELATED-DIRTY |
| `experiments/a3_measure.log` | no | G-UNRELATED-DIRTY |
| `experiments/parser_test_output.txt` | no | G-UNRELATED-DIRTY |
| `experiments/results/run.log` | no | G-UNRELATED-DIRTY |
| `pipeline/community_matcher.py` | no | G-UNRELATED-DIRTY |
| `pipeline/subtitle_analyzer.py` | no | G-UNRELATED-DIRTY |

`git status --short` collapses the hygiene-session directory into a single
`??` entry; that one entry is what the G5 snapshot counts. Internally the
directory expands to 8 files at Turn 5 (listed in §0 under "Counting
convention"). All 8 files are G-HYGIENE-SESSION and will be committed as a
single unit together with `Document/dialogue/state.json` (see §2.1 rationale)
in commit 2 of the freeze plan.

### 2.3 Already-tracked via `c6b0adc` (no worktree change — not in status)

For completeness, paths that used to be "untracked" at Turn 1/2 but are now
clean because `c6b0adc` absorbed them:

- `.agents/**`, `.claude/commands/**`, `.prompts/**`
- `AGENTS.md`, `CLAUDE.md`, `DIALOGUE-PROTOCOL.md`, `PROJECT-RULES.md`
- `Document/dialogue/state.json` and all A1–A4 session directories
  (directories 2026-04-14-phase-a1-token-logging, 2026-04-15-phase-a2-token-chunking, 2026-04-15-phase-a3-token-margin-sampling, 2026-04-15-phase-a4-generalization-plan)
- `experiments/a3_measure.py`, `experiments/a4_measure.py`,
  `experiments/chunk_size_experiment.py`,
  `experiments/_a4_cells.json`, `experiments/_a4_paths.json`,
  `experiments/_a4_transcribe_wav.py`
- `experiments/results/2026-04-14_phase-a1_token-logging.md`
- `experiments/results/2026-04-15_phase-a2_token-chunking.md`
- `experiments/results/2026-04-15_phase-a3_token-margin-sampling.md`
- `experiments/results/2026-04-15_phase-a4_raw.json`
- `experiments/results/2026-04-15_phase-a4_generalization.md`

These cover G-A4-ARTIFACT, G-DAD-SCAFFOLD, and G-A1..A3-ARTIFACT in full.

## 3. G3 coverage map

Mapping the rubric against the grouping:

| Group | G3 coverage path | Status |
|---|---|---|
| G-A4-ARTIFACT | `c6b0adc` SHA pointer is a valid freeze-commit source for G3 | **covered** |
| G-DAD-SCAFFOLD | same commit | **covered** (but out-of-scope per A5) |
| G-A1..A3-ARTIFACT | same commit | **covered** (out-of-scope) |
| G-A4-ANCHOR | no commit captures measurement-time anchor state | **gap** |
| G-HYGIENE-SESSION | session directory untracked + root `Document/dialogue/state.json` dirty | pending (planned commit in `freeze-plan.md`) |
| G-UNRELATED-DIRTY | out of scope for A4 closeout G3 | **out of scope** |

The practical consequence: Option C's "first provenance commit" has already
happened externally for the artifact side. The remaining freeze work is
**smaller and narrower** than Turn 2 assumed. Two paths remain open:

1. **Freeze-commit path** — land a commit that captures the 5 anchor files at
   their current worktree state so that A4 arithmetic is reproducible from git.
2. **Manifest path** — produce a sha256 manifest of the 5 anchor files *as
   they currently sit in the worktree* and record it in the A4 result MD. Per
   C4+A3, G3 accepts this OR the freeze commit.

Expected G5 cleanup from commits 1+2: **exactly 7 status entries** leave the
dirty set — 5 anchors (commit 1) plus `Document/dialogue/state.json` and the
collapsed `Document/dialogue/sessions/2026-04-15-a4-closeout-hygiene/` entry
(commit 2). Any other entry change is a hygiene violation.

## 4. Out-of-scope dirty state

Per C3 + A5, the following are *not* part of the A4 G3 rubric and must not be
swept into the first freeze commit:

- `pipeline/chat_analyzer.py`, `pipeline/chat_collector.py`,
  `pipeline/downloader.py`, `pipeline/monitor.py`, `pipeline/scraper.py`,
  `pipeline/settings_ui.py`, `pipeline/utils.py`
- `pipeline/community_matcher.py`, `pipeline/subtitle_analyzer.py`
- `.gitignore`, `README.md`, `prompts/청크 통합 프롬프트.md`
- `experiments/_a4_run_*.txt`, `experiments/a3_measure.log`,
  `experiments/parser_test_output.txt`, `experiments/results/run.log`

These belong to unrelated pipeline work, doc-drift, or transient log output.
They should be triaged by a later session (A4b or a dedicated hygiene cycle),
not by this closeout.

## 5. Branch note

The current branch codex/local-dirty-preserved is better-named than
Turn 2's codex/phase-a1-token-logging because it no longer claims A1 scope
exclusively. However, it is still not scoped to "A4 closeout freeze". The
freeze plan (next doc) recommends cutting a new branch codex/a4-closeout-freeze
from `c6b0adc` for the anchor-file freeze commit, leaving
codex/local-dirty-preserved alone as an in-flight workspace.

`0c078ea` is **not** a viable freeze base. Its diff vs `c6b0adc` is
README.md only, and `git merge-base c6b0adc 0c078ea` is `b62ada1` — the two
are sibling commits off the pre-A1 parent, not an ancestor chain. Cutting
the freeze branch from `0c078ea` would add no content over `c6b0adc` and
would fork provenance citations across two nearly-identical SHAs with the
same commit message. **Canonical artifact-freeze SHA = `c6b0adc`** for the
rest of this plan.
