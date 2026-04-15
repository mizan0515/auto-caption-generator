---
doc_type: dad-session-summary
session_id: 2026-04-15-a4-publish
session_status: converged
turns: 1
---

# A4 Publish — Session Summary

## Scope

Gate 2 publish only. Verify the frozen A4 provenance invariants, push the freeze
branch, open a PR with commit provenance, merge without squash or rebase, then
close the publish session locally with validators passing.

## Outcome

- Verdict: complete.
- Pre-push invariants passed exactly as handed off from Gate 1 ACK.
- The freeze branch was pushed to origin first at head c04bfce.
- PR #6 was created with commit 1 provenance, commit 1 BOM disclosure,
  hygiene provenance links, Gate 1 ACK summary reference, and the permanent
  squash/rebase ban rationale.
- GitHub could not create the merge commit cleanly against the live main tip,
  so mergeability was repaired on the same freeze branch with merge commit
  506411b in a disposable clean clone.
- PR #6 was then merged with the merge strategy only. Final main merge commit:
  28ce302.
- origin/main contains both commit 1 0a8bc65 and commit 2 c04bfce.

## Contract Results

| CP | Verdict | Notes |
|---|---|---|
| C1 | PASS | Auth probe recorded, publish session opened, root mirror updated. |
| C2 | PASS | Branch/log order, artifact byte identity, allowlists, and commit 1 BOM all re-verified. |
| C3 | PASS | Branch pushed and PR #6 opened with required provenance body. |
| C4 | PASS | Mergeability repaired with 506411b, then PR #6 merged as 28ce302 via merge strategy. |
| C5 | PASS | Packet, summaries, converged state, and both validators finished PASS. |

## Important Notes

- No forbidden rewrite was used. No squash, no rebase, no force push, no amend.
- Commit 1 and commit 2 are preserved as ancestors of origin/main.
- The Gate 1 ACK summary artifact is still local-only, so the PR body could only
  reference its repository-relative path for relay continuity.

## Deferred Work

- Gate 3 is out of scope for this session.
- Remote freeze branch deletion remains deferred.
- codex/local-dirty-preserved reconciliation remains deferred.
- G-UNRELATED-DIRTY triage remains deferred.
- claude CLI auth remains unstable and should be treated as a future-session concern.
