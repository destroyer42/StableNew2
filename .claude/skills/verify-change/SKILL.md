---
name: verify-change
description: Independently verify a StableNew diff against its acceptance contract, architecture invariants, and proportional test gates.
---
Follow `AGENTS.md`.

Do not edit during verification.

1. Read the task/work package and actual diff.
2. Map every acceptance criterion to code/test/runtime evidence.
3. Inspect affected owner boundaries rather than trusting implementation notes.
4. Run focused tests needed to establish behavior.
5. Reuse still-valid exact-SHA evidence instead of repeating expensive checks.
6. Run `git diff --check`.
7. Run `python tools/ci/run_pr_gate.py` when required by repository policy.
8. Check controller-surface and architecture impact.
9. Determine whether a security review is triggered.
10. Return PASS, FAIL, or BLOCKED with only evidence-backed findings.

A passing test suite is necessary evidence where applicable, not proof by
itself. Do not weaken tests or reinterpret acceptance to obtain a pass.
