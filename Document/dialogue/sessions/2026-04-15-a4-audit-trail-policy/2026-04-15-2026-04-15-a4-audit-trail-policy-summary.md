# 2026-04-15 — A4 Audit-Trail Policy (Session Summary)

Session id: `2026-04-15-a4-audit-trail-policy`
Status: converged (policy-only, Codex peer-verified)
Turns: 2

## Question

Should the five local-only Gate 2 / Gate 3 A4 DAD session directories be
promoted to committed audit trail on origin/main, and if so, how?

## Answer

Yes — option **(a) commit-to-main**, matching the precedent of commit 2
`c04bfce`, which already committed five earlier DAD session directories.
Execution is deferred to a dedicated follow-up session,
`2026-04-15-a4-audit-trail-execute`, that runs from the clean sister
worktree C:/github/auto-caption-generator-main and stages only the six
allowlisted session directories via an explicit path list.

## Why not the alternatives

- **Separate docs branch**: no precedent in this repo, git log origin/main
  would not surface the audit trail, and it adds permanent branch-management
  overhead. Defeats the provenance objective.
- **Keep local-only**: breaks the existing precedent and risks losing the
  exact five sessions that document how commit 1 `0a8bc65` and commit 2
  `c04bfce` reached origin/main. This is the forensic loss
  `DIALOGUE-PROTOCOL.md` is meant to guard against.

## Provenance (re-verified in this session)

- PR #6: MERGED, `mergeCommit=28ce302`
- commit 1 `0a8bc65` → ancestor of origin/main (YES)
- commit 2 `c04bfce` → ancestor of origin/main (YES)
- origin/main tip: `28ce302`
- Remote freeze branch codex/a4-closeout-freeze: absent

## Risk controls recorded in `policy.md`

- Execute from sister worktree only; never from the dirty live worktree.
- Stage by explicit six-path list; never `git add -A` / `git add .`.
- Forbid staging of root `Document/dialogue/state.json`, `.gitignore`,
  `README.md`, `prompts/*`, `pipeline/*`, `experiments/*`.
- Merge strategy only for the PR; no squash, no rebase, no force push,
  no amend. Mergeability repair path mirrors the Gate 2 publish flow.

## Handoff

Next session: `2026-04-15-a4-audit-trail-execute` (Turn 1). Seed is
fully specified in `policy.md` and `turn-01.yaml.handoff.next_task`.

## Turn 2 Notes

Codex re-verified the policy against the live repository and kept the
session converged. The decision stands: commit the six A4 session
directories later from the clean sister worktree, not from the dirty
live worktree.

Turn 1 had two documentary count errors that are now corrected:

- `Document/dialogue/sessions` currently contains **11** directories total,
  not 10.
- `git status --short` currently emits **24** lines total, not 23, because
  the audit-trail-policy session directory itself is also untracked.

These were recording errors only. Gate 2 provenance, sister-worktree
cleanliness, allowlist scope, forbidden-list scope, and validators all
passed in Turn 2.
