# Codex Work Package Template

Use this template for a bounded StableNew implementation, validation, or
documentation closeout. Keep the scope narrow and preserve the repository
authorities and exact start state.

## Objective

- Outcome:
- In scope:
- Explicit exclusions:

## Execution class and model recommendation

- Execution class: Narrow / Standard / Architectural
- Execution location: Local / Cloud
- Model recommendation (one line each, per `docs/AI_MODEL_SELECTION.md`): Claude Code model + effort; Codex model + effort
- Preferred host and why (only if one materially fits better; otherwise stay in the current session):
- Expected usage (order of magnitude, for example "about 10M cache-read, 60k output"):
- Separable hard part worth delegating to a stronger model (only if clearly separable):

## Exact start state and authorities

- Task-start timestamp with timezone (record before discovery), participating host/session IDs and package/shared-session boundary:
- Repository and branch:
- Required start SHA:
- Remote feature SHA / `origin/main`:
- Worktree state:
- Canonical docs consulted:

## Surface assessment

- Source/test/tool/config files allowed to change:
- Controller or coordinator surface touched: Yes / No
- Controller Surface Assessment:
- Architecture authority or invariant changed: Yes / No

## Acceptance and evidence reuse

- Required behavior/evidence:
- Existing exact-SHA evidence reused:
- New manual or runtime evidence:
- Known blockers or non-blocking debt:
- Existing non-blocking CI/review debt to ignore unless caused by this package:
- Review/Repair Budget: one batched repair/reverification cycle for confirmed
  current in-scope findings; stale/duplicate/already-fixed findings authorize no
  edits and consume no cycle.
- Physical/External Evidence Freeze (when applicable):
- Stop condition after the allowed repair/reverification cycle:

## Token-Efficient Validation Plan

1. Run focused changed-behavior checks.
2. Reuse unchanged exact-SHA evidence and avoid redundant expensive checks.
3. Run the prescribed gate only when source changes or a current CI verdict is
   required.
4. Verify the final diff, remote state, and working tree.

## Stop conditions

- Higher execution class or architecture decision discovered:
- A materially new blocking failure class remains or appears after the one
  allowed batched repair and independent reverification:
- Scope begins expanding into the next roadmap phase:

## Documentation impact

- `STATUS.md` (current state only: change a line when a baseline, hold, decision or direction changed; never add a PR bullet):
- Roadmap:
- Architecture:
- `CODEX_MAP.md`:
- Coding/testing:
- `AGENTS.md` (the only place rules live):

## Completion report

- Parent/final SHA:
- Files changed:
- Validation and CI:
- Main unchanged:
- Working tree clean:
- Ready for next phase: Yes / No
- Model / usage (host, actual model, effort, repair passes, result, exact start/end window and the line from
  `tools/usage_report.py --since <task-start> --until <end-after-closeout> --session <claude:ID|codex:ID> --line`;
  repeat session filters as needed; label project/shared-session totals and missing telemetry, never claim unsupported PR attribution):
