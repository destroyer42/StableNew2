# PR-UNIFY-201: Canonical Docs Reset and Architecture Constitution

## Purpose

Reset the active docs set so the repo has one consistent architecture story and
one consistent migration story.

This PR is documentation-first. It does not claim that all runtime debt is
already removed. It makes the target architecture, backlog order, and document
ownership explicit so follow-on runtime PRs can be judged against one canon.

## Files Updated

- `README.md`
- `docs/ARCHITECTURE_v2.6.md`
- `docs/StableNew Roadmap v2.6.md`
- `docs/CompletedPlans/MIGRATION_CLOSURE_EXECUTABLE_BACKLOG_v2.6-1.md`
- `docs/CompletedPlans/StableNew_ComfyAware_Backlog_v2.6.md`
- `docs/DOCS_INDEX_v2.6.md`
- `docs/archive/superseded/StableNew_Architecture_v2.6.md`

## Key Decisions Locked

- NJR is the only outer executable job contract.
- Fresh production execution is queue-only.
- `Run Now` is queue submit + immediate auto-start, not a second executor path.
- StableNew owns orchestration; backends execute only.
- Old persisted queue/history data is handled by one-time migration tooling.
- `docs/ARCHITECTURE_v2.6.md` is the only active architecture constitution.

## Why This PR Exists

Before this reset, the active docs contradicted each other on:

- PromptPack-only versus multi-surface intent
- queue versus queue-or-direct execution
- image-only versus image-plus-video orchestration
- whether the repo was already fully migrated or still carrying live compat seams

That contradiction made later migration PRs ambiguous.

## Verification

Docs-only verification performed:

- checked updated files for internal consistency
- confirmed the repo still contains the debt seams referenced by the new backlog
- confirmed current collection baseline remains `2334 collected / 1 skipped`

## Follow-On Queue

The next runtime PRs after this reset are:

1. `PR-NJR-202-Queue-Only-Submission-Contract`
2. `PR-MIG-203-One-Time-History-Queue-Migration-Tool`
3. `PR-MIG-204-Delete-Live-Legacy-Execution-Seams`
