# PR-POLISH-282 - Canonical Roadmap Video Status Harmonization

Status: Specification
Priority: MEDIUM
Effort: SMALL
Phase: Documentation Harmonization
Date: 2026-03-26

## Context & Motivation

### Current Repo Truth

The canonical roadmap summary currently contradicts later sections of the same
document and the superseded video-mapping note.

At the top of the roadmap, the current text still says AnimateDiff and
workflow-video rollout remain queued. Later in the same file, `PR-VIDEO-239`,
`PR-VIDEO-240`, and `PR-VIDEO-241` are marked completed, and the superseded
video-sequence mapping doc also correctly records them as completed.

### Specific Problem

This documentation drift makes planning, review, and branch-state
interpretation harder than necessary. The canonical roadmap should not contain
mutually contradictory repo truth.

### Why This PR Exists Now

`D-016` identified roadmap contradiction as a real canonical-doc failure. The
runtime/video branch is now far enough along that documentation ambiguity is
becoming more expensive than the edit to fix it.

### Reference

- `docs/StableNew Roadmap v2.6.md`
- `docs/PR_Backlog/MASTER_PR_SEQUENCE_FROM_CURRENT_REPO_STATE_v2.6.md`
- `docs/PR_Backlog/REVISED_MINI_ROADMAP_PR_ORDER_v2.6.md`
- `docs/PR_Backlog/VIDEO_AND_SECONDARY_MOTION_REMAINING_WORK_SEQUENCE_v2.6.md`
- `docs/Research Reports/D-016-Branch-Review-Since-2026-03-22-2205.md`

## Goals & Non-Goals

### Goals

1. Remove contradictory roadmap language about AnimateDiff and workflow-video
   still being queued.
2. Align the top-level roadmap summary with the already completed
   `PR-VIDEO-239` through `PR-VIDEO-241` entries.
3. Keep the superseded video-sequence note accurate and clearly subordinate to
   the canonical roadmap and master queue docs.
4. Make the remaining work statements describe the actual current repo state.

### Non-Goals

1. Do not alter runtime code in this PR.
2. Do not renumber the canonical roadmap.
3. Do not widen this into a full wording polish across all docs.
4. Do not change completed-PR facts unless a verified repo-truth error is found.

## Guardrails

1. This is a docs-only harmonization PR.
2. No runtime, builder, queue, runner, or GUI files may change.
3. Preserve the canonical queue ordering unless there is a verified factual
   mismatch in the docs.
4. Keep superseded docs marked as superseded rather than reviving them as active
   planning surfaces.

## Allowed Files

### Files to Create

| File | Purpose |
| ------ | ------- |
| None expected | |

### Files to Modify

| File | Reason |
| ------ | ------ |
| `docs/StableNew Roadmap v2.6.md` | Remove contradictory status language and align summary with completed video PRs |
| `docs/PR_Backlog/MASTER_PR_SEQUENCE_FROM_CURRENT_REPO_STATE_v2.6.md` | Only if a mirrored wording correction is needed |
| `docs/PR_Backlog/REVISED_MINI_ROADMAP_PR_ORDER_v2.6.md` | Only if a mirrored wording correction is needed |
| `docs/PR_Backlog/VIDEO_AND_SECONDARY_MOTION_REMAINING_WORK_SEQUENCE_v2.6.md` | Only if a cross-reference or superseded note needs tightening |
| `docs/Research Reports/D-016-Branch-Review-Since-2026-03-22-2205.md` | Optional link-back note if useful |

### Forbidden Files

| File/Directory | Reason |
| ---------------- | ------ |
| `src/**` | No runtime code changes |
| `tests/**` | No test changes in this docs-only PR |
| `docs/ARCHITECTURE_v2.6.md` | No architecture changes are proposed |
| `docs/GOVERNANCE_v2.6.md` | No governance changes are proposed |

## Implementation Plan

### Step 1: Identify the contradictory roadmap statements

Pinpoint and list the exact lines where the roadmap summary diverges from later
completed-status entries.

Files:

- modify no files yet

Tests:

- none

### Step 2: Harmonize the canonical roadmap summary

Update the top-level summary and any remaining “queued” language so it matches
the completed `PR-VIDEO-239` through `PR-VIDEO-241` entries and the current repo
truth.

Required details:

- preserve the distinction between completed backend/runtime rollout and still
  remaining follow-on UX/polish work
- avoid overstating “fully done” if the repo truth is “feature sequence
  completed, follow-on polish remains”

Files:

- modify `docs/StableNew Roadmap v2.6.md`

### Step 3: Mirror any necessary wording cleanup in queue-order docs

If the master queue or revised mini-roadmap repeat the contradictory wording,
tighten them to match the canonical roadmap.

Files:

- modify `docs/PR_Backlog/MASTER_PR_SEQUENCE_FROM_CURRENT_REPO_STATE_v2.6.md`
- modify `docs/PR_Backlog/REVISED_MINI_ROADMAP_PR_ORDER_v2.6.md`
- modify `docs/PR_Backlog/VIDEO_AND_SECONDARY_MOTION_REMAINING_WORK_SEQUENCE_v2.6.md`
  only if a cross-reference sentence needs adjustment

### Step 4: Final consistency read

Do one final pass across the touched docs to ensure they all describe the same
current repo truth and do not reintroduce the old contradiction.

Files:

- no new files expected

## Testing Plan

### Unit Tests

- none

### Integration Tests

- none

### Journey or Smoke Coverage

- manual document consistency read across the touched docs

### Manual Verification

1. Confirm the roadmap no longer says AnimateDiff/workflow-video remain queued.
2. Confirm completed video PR entries remain intact.
3. Confirm the superseded video-sequence note still clearly points to the
   canonical roadmap and master queue as the source of truth.

## Verification Criteria

### Success Criteria

1. `docs/StableNew Roadmap v2.6.md` no longer contradicts itself about video
   completion status.
2. Any mirrored queue-order docs tell the same story.
3. The docs clearly distinguish completed backend/runtime rollout from any
   remaining follow-on polish.

### Failure Criteria

1. The roadmap still contains contradictory queued/completed status language.
2. The fix accidentally changes runtime facts instead of just harmonizing them.
3. The PR widens into code changes.

## Risk Assessment

### Low-Risk Areas

- wording harmonization within docs-only scope

### Medium-Risk Areas with Mitigation

- overstating completion beyond current repo truth
  - Mitigation: keep wording precise and grounded in already completed PR
    records and passing reviewed test surfaces

### High-Risk Areas with Mitigation

- none expected if the PR stays docs-only

### Rollback Plan

- revert the doc edits if the harmonized wording is found to misstate repo truth

## Tech Debt Analysis

### Debt Removed

- contradictory canonical roadmap status language
- confusion between completed video backend rollout and remaining follow-on UX
  or polish work

### Debt Intentionally Deferred

- broader doc wording polish outside the specific video-status contradiction
  - next PR owner: future documentation cleanup only if needed

## Documentation Updates

- this PR is itself the documentation update
- no docs-index change is required unless repo policy treats new backlog-spec
  additions as indexable, which is not currently expected

## Dependencies

### Internal Module Dependencies

- none beyond the touched docs

### External Tools or Runtimes

- none

## Approval & Execution

Planner: Codex
Executor: Codex
Reviewer: Human
Approval Status: Pending

## Next Steps

1. managed end-to-end AnimateDiff runtime verification
2. managed end-to-end Comfy workflow-video verification
3. broader UX tranche cleanup after runtime/doc stability work

