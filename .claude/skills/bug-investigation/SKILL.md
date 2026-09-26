---
name: bug-investigation
description: Reproduce, isolate, root-cause, repair, and regression-test a StableNew defect without speculative cleanup.
---
Follow `AGENTS.md`.

Use this skill when the task is primarily a defect, crash, incorrect behavior,
or regression.

1. Capture the symptom and expected behavior.
2. Establish current branch/HEAD/worktree and relevant runtime/environment.
3. Reproduce with the smallest safe deterministic path available.
4. Trace from observed failure to the owning boundary. Prefer logs, tests,
   state transitions, and current code over guesses.
5. Maintain competing hypotheses until evidence eliminates them.
6. Distinguish root cause from correlated symptoms.
7. Implement the smallest fix at the owner boundary; do not paper over the
   symptom in a caller/UI if the defect is lower-level.
8. Add a regression test that fails for the old behavior when practical.
9. Run focused validation, `git diff --check`, and required repo gates.
10. Report any unproven hypothesis explicitly.

For GPU/process/hardware investigations, observation does not establish
component attribution. Do not change firmware, drivers, models, or external
runtime state unless the work package explicitly authorizes that variable.
