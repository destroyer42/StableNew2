# StableNew Agentic Coding Usage Guide

Status: operator guide

This guide explains how to use the StableNew agent stack without creating shadow governance.

## Read order

Read these first:

1. `AGENTS.md`
2. `docs/ARCHITECTURE_v2.6.md`
3. `docs/GOVERNANCE_v2.6.md`
4. `docs/StableNew_Coding_and_Testing_v2.6.md`
5. `docs/PR_TEMPLATE_v2.6.md`

Then use:

- `.github/copilot-instructions.md` for the active executor brief
- `.github/agents/` for specialist roles
- `.github/instructions/` for path-scoped rules

## Active specialist set

Use these agent profiles for new work:

- `controller_lead_engineer.md`
- `implementer.md`
- `gui.md`
- `pipeline_runtime.md`
- `tester.md`
- `docs.md`
- `refactor.md`

Archived agent files are reference-only and should not be used for new tasks.

## Recommended workflow

1. Write or approve a PR-scoped plan with Allowed Files and Forbidden Files.
2. Implement inside that scope only.
3. Run targeted verification plus broader validation as appropriate.
4. Update docs when behavior or active guidance changes.
5. Archive stale instructions instead of leaving them active.

## Good task shape

Good agent tasks include:

- a clear problem statement
- explicit allowed file boundaries
- exact tests to run
- acceptance criteria
- rollback expectations

Bad agent tasks include:

- open-ended architecture changes
- vague cleanup requests
- runtime-critical work without a bounded plan
- requests that rely on obsolete docs or retired file layouts

## Notes for repository maintenance

- Root `AGENTS.md` is the canonical agent contract.
- `.github/copilot-instructions.md` is the active executor brief.
- `.github/PULL_REQUEST_TEMPLATE.md` is the GitHub-facing wrapper around the canonical PR template.
- `docs/archive/agents/2026-agentic-refresh/` stores retired agent and process guidance from before the refresh.
