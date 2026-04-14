---
doc_type: dad-session-artifact
session_id: 2026-04-15-a4-closeout-hygiene
artifact: freeze-plan
turn_origin: 3
revised_in_turn: 5
status: execute-ready
---

# A4 Closeout Hygiene — Freeze Plan (Option C)

Drafted in Turn 3, revised in Turn 5 per Turn 4 peer amendments A1/A2/A3/A4.
Describes the minimal git-mutation slice that would close G3 for A4 once a
follow-up session is allowed to switch from plan-only to execute-with-git.
No `git add`, `git commit`, `git reset`, `git stash`, `git push`, or
`gh pr create` is performed in Turn 3 or Turn 5. Freeze execution is
deferred to a dedicated follow-up session.

## 0. Preconditions

Derived from `provenance-boundary.md`:

- Canonical artifact-freeze SHA is `c6b0adc`. `0c078ea` is a README-only
  sibling (merge-base `b62ada1`) and not used.
- The remaining G3 gap is only the 5-file anchor set (G-A4-ANCHOR).
- The current hygiene session directory is still untracked (one collapsed
  `??` entry) and the root `Document/dialogue/state.json` is dirty.
- Out-of-scope dirty state (G-UNRELATED-DIRTY) must be preserved, not swept.

## 1. Branch strategy

Do not commit freeze work on the current branch (codex/local-dirty-preserved).
That branch is semantically "a workspace that intentionally keeps dirty
state"; a freeze commit landing there would mix provenance with in-flight
work.

Recommended:

1. Create a dedicated hygiene branch (codex/a4-closeout-freeze) anchored at
   artifact freeze commit c6b0adc. Suggested command: git switch -c
   codex/a4-closeout-freeze c6b0adc.
2. All freeze work lands on this branch. The codex/local-dirty-preserved
   branch is untouched.
3. Later, fast-forward `main` or merge via PR once ACK verifies G1–G5.

### Why not start from `main` directly

Using `main` as the freeze base would force the new branch to replay the A4
artifact set (result MDs + session YAMLs + `experiments/a4_measure.py`) from
scratch, because `main` does not currently contain `c6b0adc`'s tree. Any
replay risks (a) diverging even slightly from the artifact bytes frozen in
`c6b0adc`, which would reopen G3 on the artifact side, and (b) creating a
third parallel commit with the same "Add DAD artifacts and A1-A4 experiment
closeout" message, compounding the existing `c6b0adc`/`0c078ea` ambiguity.
Cutting from `c6b0adc` keeps the artifact side frozen as-is and scopes the
new commits to the anchor-only gap. Merging to `main` is a separate,
post-ACK concern.

## 2. Commit slice plan

Three commits, small and reviewable. Each has an explicit file allowlist.

### Commit 1 — anchor-file measurement-time freeze

Purpose: close the G-A4-ANCHOR gap so `G3` can cite a freeze-commit SHA.

Allowlist (exactly these 5 files, nothing else):

- `pipeline/config.py`
- `pipeline/main.py`
- `pipeline/chunker.py`
- `pipeline/claude_cli.py`
- `pipeline/summarizer.py`

Commit-message shape:

```
Freeze pipeline anchors at A4 measurement-time state

Captures the 5-file measurement anchor set (config, main, chunker,
claude_cli, summarizer) at the worktree state used for Phase A4.
Required by G3 of the A4 closeout ACK rubric. No behavioural change
intended over the measurement run.

Anchors:
- pipeline/config.py:18-28 chunk_max_tokens=None
- pipeline/main.py:186-197 precedence
- pipeline/chunker.py:156-257 split_by_tokens + dispatcher
- pipeline/claude_cli.py:23-58 _log_usage
- pipeline/summarizer.py:59,:121 _build_chunk_prompt

Session: Document/dialogue/sessions/2026-04-15-a4-closeout-hygiene
```

Expected `git show --stat` — exactly 5 files changed. Any other file in the
diff is a hygiene violation and the commit must be aborted.

### Commit 2 — hygiene session artifacts + root state

Purpose: land the G-HYGIENE-SESSION directory together with the companion
update to root `Document/dialogue/state.json`, so the session itself is
reproducible and the turn packets become citable via SHA.

Allowlist (exactly these paths):

- `Document/dialogue/state.json` (already modified vs `c6b0adc`)
- `Document/dialogue/sessions/2026-04-15-a4-closeout-hygiene/state.json`
- `Document/dialogue/sessions/2026-04-15-a4-closeout-hygiene/turn-01.yaml`
- `Document/dialogue/sessions/2026-04-15-a4-closeout-hygiene/turn-02.yaml`
- `Document/dialogue/sessions/2026-04-15-a4-closeout-hygiene/turn-03.yaml`
- `Document/dialogue/sessions/2026-04-15-a4-closeout-hygiene/turn-04.yaml`
- `Document/dialogue/sessions/2026-04-15-a4-closeout-hygiene/turn-05.yaml`
- `Document/dialogue/sessions/2026-04-15-a4-closeout-hygiene/provenance-boundary.md`
- `Document/dialogue/sessions/2026-04-15-a4-closeout-hygiene/freeze-plan.md`
- Optionally a later `summary.md` if the closeout session produces one.

Root `Document/dialogue/state.json` **must** travel with this commit, not
with a separate scaffolding commit — its dirty diff against `c6b0adc` is
exactly the hygiene-session turn/decision updates, so splitting it would
land incoherent state snapshots in two different SHAs.

Expected `git show --stat` row count for commit 2 at execute time: 9 files
(1 root state + 8 session files). Any extra file = hygiene violation, abort.

### Commit 3 — sha256 manifest (deferred; optional only)

**Deferred by default.** Per C2+A4, commit 3 is not produced in the freeze
execution session unless a later ACK review explicitly requires non-git
provenance. G3 is an OR: the freeze-commit SHA from commit 1 already
satisfies G3 on its own. Skipping commit 3 keeps the freeze session to a
tight two-commit slice and avoids re-opening the A4 result docs.

If a later ACK demands it, commit 3 would add:

- `experiments/results/2026-04-15_phase-a4_anchor-manifest.sha256`
  (new file, 5 lines, one `sha256  path` pair per anchor, computed against
  the worktree *before* commit 1 lands — i.e. against the same content that
  commit 1 captures).

Do **not** re-open `experiments/results/2026-04-15_phase-a4_generalization.md`
to add the manifest inline. That MD is frozen in `c6b0adc`. Cite the
manifest path from a new closeout addendum only if ACK explicitly asks for it.

## 3. pipeline/* handling

The other 11 dirty pipeline files (and the 2 untracked ones) are **explicitly
excluded** from the three commits above. They remain dirty on
codex/local-dirty-preserved, not on codex/a4-closeout-freeze.

Procedure to keep them isolated:

1. Before commit 1, verify with `git status --short` that only the 5 anchor
   files are staged. Use `git add -- <exact path>` for each, not `git add -A`.
2. After commit 1, run `git status --short` again and compare against the
   allowlist diff described in §5 (G5).
3. If any non-anchor pipeline file shows up as staged, `git restore --staged
   <path>` before proceeding.

## 4. G3 interpretation

Per C4 + amendment A3 of Turn 2:

- G3 is satisfied if **either** a measurement-time freeze commit SHA
  **or** a sha256 manifest is available for the anchor set, not both.
- Commit 1 provides the freeze-commit SHA path.
- Commit 3 provides the sha256 manifest path.
- Both are included above so the hygiene session can offer ACK either form.

Recommended citation form for the A4 close-ack follow-up:

> G3 — anchor provenance: freeze commit `<sha>` on branch
> codex/a4-closeout-freeze, covering exactly 5 files:
> `pipeline/config.py`, `pipeline/main.py`, `pipeline/chunker.py`,
> `pipeline/claude_cli.py`, `pipeline/summarizer.py`. Manifest
> `experiments/results/2026-04-15_phase-a4_anchor-manifest.sha256`
> supplements.

## 5. G5 interpretation (allowlist diff)

Per C4 + A4, G5 compares before/after `git status --short` against an
allowlist captured at execute start.

### Before snapshot (live at Turn 5; 16 M + 8 ?? = 24 entries)

```
 M .gitignore
 M Document/dialogue/state.json
 M README.md
 M pipeline/chat_analyzer.py
 M pipeline/chat_collector.py
 M pipeline/chunker.py
 M pipeline/claude_cli.py
 M pipeline/config.py
 M pipeline/downloader.py
 M pipeline/main.py
 M pipeline/monitor.py
 M pipeline/scraper.py
 M pipeline/settings_ui.py
 M pipeline/summarizer.py
 M pipeline/utils.py
 M prompts/청크 통합 프롬프트.md
?? Document/dialogue/sessions/2026-04-15-a4-closeout-hygiene/
?? experiments/_a4_run_1h.txt
?? experiments/_a4_run_3h.txt
?? experiments/a3_measure.log
?? experiments/parser_test_output.txt
?? experiments/results/run.log
?? pipeline/community_matcher.py
?? pipeline/subtitle_analyzer.py
```

### Expected after-snapshot, after commits 1+2 (on codex/a4-closeout-freeze; 10 M + 7 ?? = 17 entries)

```
 M .gitignore
 M README.md
 M pipeline/chat_analyzer.py
 M pipeline/chat_collector.py
 M pipeline/downloader.py
 M pipeline/monitor.py
 M pipeline/scraper.py
 M pipeline/settings_ui.py
 M pipeline/utils.py
 M prompts/청크 통합 프롬프트.md
?? experiments/_a4_run_1h.txt
?? experiments/_a4_run_3h.txt
?? experiments/a3_measure.log
?? experiments/parser_test_output.txt
?? experiments/results/run.log
?? pipeline/community_matcher.py
?? pipeline/subtitle_analyzer.py
```

Exact diff vs before: **exactly 7 status entries** become clean.

Removed (commit 1): 5 anchors
- `M pipeline/chunker.py`
- `M pipeline/claude_cli.py`
- `M pipeline/config.py`
- `M pipeline/main.py`
- `M pipeline/summarizer.py`

Removed (commit 2): 2 entries
- `M Document/dialogue/state.json`
- `?? Document/dialogue/sessions/2026-04-15-a4-closeout-hygiene/`

Added: none. Commit 3 (manifest) is deferred by default, so no new `??`
line appears in the baseline after-snapshot.

### G5 verdict rule

G5 = PASS iff `git status --short` after commits matches the allowlist
above exactly. Any extra `M` or `??` entry = FAIL, stop, investigate.

## 6. Scope non-goals

Explicitly not part of this freeze plan:

- Fixing the `transcribe.py` `-c copy` keyframe-cut bug.
- Start-offset diversification for A4b.
- Genre-axis acquisition via the Chzzk downloader.
- Committing `pipeline/community_matcher.py` / `subtitle_analyzer.py` or the
  other dirty pipeline files.
- Editing any file under `Document/dialogue/sessions/2026-04-15-phase-a4-generalization-plan/`
  (A4 frozen session).

Each of these would need its own session.

## 7. Turn 5 resolutions + remaining questions

### Resolved in Turn 5 (per Turn 4 amendments)

- **Canonical artifact-freeze SHA** = `c6b0adc`. `0c078ea` is a
  README-only sibling (merge-base `b62ada1`) and is not referenced.
- **Freeze branch base** = `c6b0adc`, not `main`. Rationale in §1.
- **Commit 3 (sha256 manifest)** = deferred. Not executed in the freeze
  session unless a later ACK review explicitly demands non-git provenance.

### Still open (for the follow-up execute session)

- Does ACK explicitly require pushing codex/a4-closeout-freeze to origin,
  or is a local SHA sufficient for the current round? (Default assumption:
  local SHA until ACK says otherwise; per PROJECT-RULES no direct push to
  `main` is allowed, and the freeze branch is not `main`.)
- If the user reviews this plan and wants commit 3 included in the same
  session, re-introduce it as the third commit with the allowlist in §2.
- Whether to clean up codex/local-dirty-preserved afterwards or let it
  keep carrying the G-UNRELATED-DIRTY state indefinitely.
