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
- Model and reasoning:
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

## Token-Efficient Validation Plan

1. Run focused changed-behavior checks.
2. Reuse unchanged exact-SHA evidence and avoid redundant expensive checks.
3. Run the prescribed gate only when source changes or a current CI verdict is
   required.
4. Verify the final diff, remote state, and working tree.

## Stop conditions

- Higher execution class or architecture decision discovered:
- More than two materially different failure classes:
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
