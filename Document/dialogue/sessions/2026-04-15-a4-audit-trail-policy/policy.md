---
doc_type: dad-policy
session_id: 2026-04-15-a4-audit-trail-policy
policy_status: proposed
scope: a4-session-artifacts-only
---

# A4 DAD Session Audit-Trail Policy

## Context

As of this session (2026-04-15), the repository contains two populations of DAD
session directories under `Document/dialogue/sessions/`:

**Tracked on origin/main (via commit 2 `c04bfce`):**

- `2026-04-14-phase-a1-token-logging`
- `2026-04-15-a4-closeout-hygiene`
- `2026-04-15-phase-a2-token-chunking`
- `2026-04-15-phase-a3-token-margin-sampling`
- `2026-04-15-phase-a4-generalization-plan`

**Untracked, local-only (in the current worktree only):**

- `2026-04-15-a4-closeack-ack`
- `2026-04-15-a4-freeze-execute`
- `2026-04-15-a4-publish`
- `2026-04-15-a4-postmerge-cleanup`
- `2026-04-15-a4-local-cleanup`
- `2026-04-15-a4-audit-trail-policy` (this session)

The first five of the untracked set are the Gate 2 / Gate 3 operational
sessions that executed between the hygiene commit and the final local-cleanup
close. The sixth is this policy session itself.

## Source-of-Truth Anchor

`PROJECT-RULES.md` ranks `Document/` as the sixth source of authority for
operational documents and session artifacts. `DIALOGUE-PROTOCOL.md` specifies
that each session lives at `Document/dialogue/sessions/{session-id}/` and
closed sessions require a summary artifact. Neither document mandates local-only
storage; both treat the repository tree as the canonical location. That treats
*committing* these directories as the aligned default and *not committing* them
as an exception that needs its own justification.

## Options Considered

### (a) Commit to main (recommended)

- **Pros.** Matches the existing repository precedent exactly (commit 2
  already committed five peer session directories). Makes the Gate 2 / Gate 3
  provenance narrative forensically reachable via `git log` and `git show`,
  not just via a specific worktree. Survives worktree deletion, machine
  migration, and fresh clones. Consistent with `DIALOGUE-PROTOCOL.md`
  treating the session directory layout as repository state, not scratch.
- **Cons.** Requires a commit path that does not mix with the current
  codex/g-unrelated-dirty-salvage feature work. Requires discipline on
  which files to include (see *Staging Allowlist*). Adds a second merge to
  origin/main beyond the already-merged `28ce302`.

### (b) Separate docs branch that never merges to main

- **Pros.** Cleanly isolates audit trail from feature branches at the
  expense of having two long-lived mainlines.
- **Cons.** No precedent in this repo. Future readers must know to look
  there. git log origin/main would not surface the audit trail, which
  defeats the provenance objective. Adds branch-management overhead for
  every new session.

### (c) Keep local-only

- **Pros.** Zero risk of mixing with feature work. Zero extra commit.
- **Cons.** Breaks the existing precedent. Loses the audit trail if the
  worktree is deleted, moved, or re-cloned. Means the five Gate 2 / Gate 3
  sessions — the exact set that documents how commit 1 `0a8bc65` and commit 2
  `c04bfce` reached origin/main — would exist only on one machine. That
  is exactly the forensic scenario `DIALOGUE-PROTOCOL.md` is meant to
  guard against.

## Decision

**Adopt option (a).** Commit the five Gate 2 / Gate 3 session directories to
origin/main using the standard repository flow (branch → PR → merge
strategy only; no squash, no rebase, no force push, no amend), matching the
path that commit 2 `c04bfce` used for the earlier five. Include this policy
session directory in the same commit so the audit trail covers its own
decision, except for the parts of the current turn that are still being
authored at execution time.

This decision is policy-only in this session. Actual staging and commit are
deferred to a dedicated execute session (see *Handoff*).

## Execution Path (for the follow-up session)

The key constraint is that the current worktree
C:/github/auto-caption-generator holds codex/g-unrelated-dirty-salvage
with eleven modified files plus two new untracked pipeline modules
(`pipeline/community_matcher.py`, `pipeline/subtitle_analyzer.py`) and scratch
experiment outputs. Staging from this worktree risks accidental inclusion of
feature work. The sister worktree C:/github/auto-caption-generator-main is
currently clean on main@28ce302 and is the correct execution surface.

### Step-by-step plan

1. Run from C:/github/auto-caption-generator-main:

   ```
   git fetch origin
   git pull --ff-only origin main
   git switch -c codex/a4-audit-trail
   ```

2. Copy the five Gate 2 / Gate 3 session directories and the policy session
   directory from the live worktree into the sister worktree. Suggested path
   uses `robocopy` with `/MIR` per directory, or equivalent, producing the
   tree:

   ```
   Document/dialogue/sessions/2026-04-15-a4-closeack-ack/
   Document/dialogue/sessions/2026-04-15-a4-freeze-execute/
   Document/dialogue/sessions/2026-04-15-a4-publish/
   Document/dialogue/sessions/2026-04-15-a4-postmerge-cleanup/
   Document/dialogue/sessions/2026-04-15-a4-local-cleanup/
   Document/dialogue/sessions/2026-04-15-a4-audit-trail-policy/
   ```

3. Confirm nothing else changed in the sister worktree:

   ```
   git -C C:/github/auto-caption-generator-main status --short
   ```

   The only `??` / `A` entries must be inside
   Document/dialogue/sessions/2026-04-15-a4-*. No pipeline/, no
   experiments/, no `.gitignore`, no prompts/, no `README.md`, no root
   Document/dialogue/state.json.

4. Stage via explicit path list (no `git add -A`, no `git add .`):

   ```
   git add Document/dialogue/sessions/2026-04-15-a4-closeack-ack \
           Document/dialogue/sessions/2026-04-15-a4-freeze-execute \
           Document/dialogue/sessions/2026-04-15-a4-publish \
           Document/dialogue/sessions/2026-04-15-a4-postmerge-cleanup \
           Document/dialogue/sessions/2026-04-15-a4-local-cleanup \
           Document/dialogue/sessions/2026-04-15-a4-audit-trail-policy
   ```

5. Verify the stage with `git diff --cached --name-only` — the output must
   list only files inside the six allowlisted directories.

6. Commit with a subject that explicitly declares this is the A4 Gate 2 /
   Gate 3 audit-trail continuation of commit 2 `c04bfce`. The commit body
   should link to commit 1 `0a8bc65`, commit 2 `c04bfce`, and PR #6 merge
   commit `28ce302` so future readers can reconstruct the whole chain from
   `git log`.

7. Push, open a PR against main, and merge with the merge strategy only.
   Squash and rebase are forbidden because they would destroy the audit-trail
   granularity the policy is trying to preserve.

### Staging allowlist — what is NOT committed in the execute session

- Document/dialogue/state.json (root). This file is a live pointer to the
  currently active session and is volatile by design. A committed snapshot
  of it would be stale by the next session.
- The live worktree's pipeline/ modifications and the untracked modules
  `pipeline/community_matcher.py` and `pipeline/subtitle_analyzer.py`. These
  are feature work living on codex/g-unrelated-dirty-salvage; they belong
  to a different commit story.
- `experiments/_a4_run_1h.txt`, `experiments/_a4_run_3h.txt`,
  `experiments/a3_measure.log`, `experiments/parser_test_output.txt`,
  `experiments/results/run.log`. These look like scratch / .gitignore
  candidates, not deliverables.
- `.gitignore`, `README.md`, and `prompts/청크 통합 프롬프트.md`. These
  are live worktree edits whose intent is not yet clear.

### Risk controls

- Do not run any `git add` from the live worktree
  C:/github/auto-caption-generator. Staging from there would have to
  coexist with the dirty set and is the most likely source of accidental
  mixing.
- Do not include the final `summary.md` of *this* policy session's Turn 2
  (peer-verify) if that turn has not been written by the time the execute
  session copies the directory. Either copy after Turn 2 closes or accept a
  Turn-1-only snapshot and record that in the execute session's commit body.
- Do not amend or rebase. If the PR is unmergeable, use a branch-local merge
  commit in a disposable clean clone, exactly as Gate 2 publish did for PR
  #6.

## Non-Goals

- Redefining the session-directory schema.
- Retroactively committing earlier sessions that already exist on
  origin/main (they are already committed by commit 2).
- Committing pipeline feature work or experiment scratch output.
- Changing `PROJECT-RULES.md` or `DIALOGUE-PROTOCOL.md` wording. Those
  documents already align with committing session artifacts; no edit is
  needed to support this policy.

## Followup Session Seed

Create `Document/dialogue/sessions/2026-04-15-a4-audit-trail-execute/`
(Turn 1) with the scope set to "execute step 1 through step 7 above, produce
a PR, and merge with the merge strategy only." The execute session must
re-check Gate 2 provenance before and after each mutation and must run both
validators before closing.
