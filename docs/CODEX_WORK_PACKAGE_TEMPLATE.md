# Codex Work Package Template

Use this template for a bounded StableNew implementation, validation, or
documentation closeout. Keep the scope narrow and preserve the repository
authorities and exact start state.

## Objective

- Outcome:
- In scope:
- Explicit exclusions:

## Execution profile and model recommendation

- Execution class: Narrow / Standard / Architectural
- Execution location: Local / Cloud
- Codex model + effort (currently available):
- Claude Code model + effort (currently available):
- Preferred host (only if one materially fits better; otherwise stay in the current session):
- Why this profile minimizes expected successful-work cost:

## Exact start state and authorities

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

- `STATUS.md`:
- Roadmap:
- Architecture:
- `CODEX_MAP.md`:
- Coding/testing:
- `AGENTS.md`:

## Completion report

- Parent/final SHA:
- Files changed:
- Validation and CI:
- Main unchanged:
- Working tree clean:
- Ready for next phase: Yes / No
