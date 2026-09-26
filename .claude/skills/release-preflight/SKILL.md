---
name: release-preflight
description: Make accepted StableNew work PR-ready with deterministic checks, scoped commit/push, and CI/review closeout while keeping main/release under owner control.
---
Follow `AGENTS.md`.

1. Confirm the current branch is not `main`.
2. Confirm intended diff/untracked files and unrelated work preservation.
3. Run `git diff --check`.
4. Confirm focused verification remains valid.
5. Run `python tools/ci/run_pr_gate.py` when required.
6. Confirm required canonical docs were updated only where truth changed.
7. Confirm independent verifier/security findings are closed or explicitly
   accepted.
8. Prepare a concise commit and PR body using the repository template.
9. When authorized, push the feature branch and open the PR.
10. Report required CI and remaining review state.

Never merge, direct-push to `main`, force-push shared history, publish a
release, deploy externally, or mutate production secrets without explicit owner
approval.
