# PR-CLEANUP-057: Recommendation 1 Closeout and Duplicate Txt2Img Audit

**Status**: Implemented
**Priority**: HIGH
**Effort**: SMALL
**Phase**: Phase 0 Closeout
**Date**: 2026-03-16
**Implementation Date**: 2026-03-16

## Context & Motivation

### Problem Statement
Recommendation #1 in the revised Top 20 still describes duplicate txt2img execution as active debt, and the dedicated debt note still describes the old CLI/legacy executor split as unresolved.

### Why This Matters
That documentation is now stale. The live repo already routes the CLI through NJR and `run_njr()`, and the old duplicate executor path is gone. Leaving the old writeup active misdirects future planning.

### Current Architecture
- `src/cli.py` builds a canonical NJR via `build_cli_njr(...)`
- `PipelineRunner.run_njr(...)` is the active runner entrypoint
- `Pipeline.run_txt2img_stage(...)` is the live txt2img executor
- recommendation and debt docs still describe the pre-consolidation state

### Reference
- `docs/StableNew_Revised_Top20_Recommendations.md`
- `docs/D-TECH-DEBT-001-Duplicate-Txt2Img-Paths.md`
- `src/cli.py`
- `src/pipeline/cli_njr_builder.py`
- `src/pipeline/executor.py`

## Goals & Non-Goals

### Goals
1. Mark recommendation #1 as implemented-with-closeout rather than active migration work.
2. Rewrite the duplicate txt2img debt note so it reflects the current codebase.
3. Add one deterministic invariant test proving the retired executor entrypoints do not reappear.
4. Remove dead temp harnesses that still mention `run_full_pipeline()`.

### Non-Goals
1. Do not change runtime behavior in `src/`.
2. Do not perform the remaining NJR-only migration work in queue/history/controllers here.
3. Do not rewrite the README or broader docs package in this PR.

## Allowed Files

### Files to Create
| File | Purpose | Lines (Est.) |
|------|---------|--------------|
| `docs/PR_MAR26/PR-CLOSE-057-Recommendation-1-Closeout-and-Duplicate-Txt2Img-Audit.md` | PR spec and implementation record | 180 |
| `tests/pipeline/test_txt2img_path_closeout_invariants.py` | guard against reintroducing retired txt2img executor entrypoints | 60 |

### Files to Modify
| File | Reason | Lines Changed (Est.) |
|------|--------|----------------------|
| `docs/StableNew_Revised_Top20_Recommendations.md` | close recommendation #1 and refresh stale collect-only evidence | 40 |
| `docs/D-TECH-DEBT-001-Duplicate-Txt2Img-Paths.md` | rewrite stale debt note to current-state closeout audit | 140 |
| `tests/gui/_tmp_test.py` | remove dead temp harness carrying retired path references | 40 |

### Forbidden Files (DO NOT TOUCH)
| File/Directory | Reason |
|----------------|--------|
| `src/**` | phase-0 closeout PR must not alter runtime behavior |
| `README.md` | broader docs refresh belongs to recommendation #13 |
| `docs/DOCS_INDEX_v2.6.md` | no active canonical source locations are changing here |

## Implementation Plan

### Step 1: Rewrite stale recommendation language
Update recommendation #1 so it states the migration is complete and only docs/invariant cleanup remains. Refresh the stale `pytest --collect-only` evidence in recommendation #5.

### Step 2: Rewrite duplicate-path debt note
Replace the discovery-era debt writeup with a closeout audit that records:
- the old problem
- the current resolved state
- the exact live entrypoints
- residual adjacent work that belongs to other recommendations

### Step 3: Add invariant coverage
Add a deterministic test that scans live `src/**/*.py` and active `tests/**/*.py` for the retired entrypoints:
- `run_full_pipeline(`
- `_run_full_pipeline_impl(`
- `def run_txt2img(`
- `def _run_txt2img_impl(`

### Step 4: Remove dead temp harnesses
Delete `tests/_tmp_test.py.skip` and `tests/gui/_tmp_test.py`, which still carry legacy `run_full_pipeline()` references and no longer provide value.

## Testing Plan

### Unit Tests
- `tests/pipeline/test_txt2img_path_closeout_invariants.py`

### Integration Tests
- none

### Journey Tests
- none

### Manual Testing
1. Read recommendation #1 and confirm it no longer proposes redoing a completed migration.
2. Read the duplicate-path debt note and confirm it now reflects current reality.
3. Grep for retired entrypoints and confirm only archived or intentionally skipped references remain absent from live code.

## Verification Criteria

### Success Criteria
1. Recommendation #1 is marked as closeout-only work.
2. The duplicate txt2img debt note reflects the post-consolidation state.
3. Active tests enforce that retired executor entrypoints do not reappear.
4. No live `src/` or active `tests/` references to the retired entrypoints remain.

### Failure Criteria
- recommendation #1 still reads like an active executor migration
- debt docs still describe the CLI as using the retired path
- the invariant test allows retired entrypoints back into active code

## Risk Assessment

### Low Risk Areas
Documentation rewrite and a grep-style invariant test.

### Medium Risk Areas
Overstating completion if adjacent migration work is conflated with recommendation #1.
- **Mitigation**: explicitly separate executor-path closure from queue/history/controller legacy cleanup.

### High Risk Areas
None expected.

### Rollback Plan
Revert the docs rewrite, delete the invariant test, and restore the removed temp harnesses if this closeout is found to misstate the runtime.

## Tech Debt Analysis

## Tech Debt Removed
- stale recommendation debt around duplicate txt2img execution
- stale debt note that no longer matches the code
- dead temp harnesses carrying retired-path references

## Tech Debt Added
- None expected

**Net Tech Debt**: -3

## Architecture Alignment

### Enforces Architecture v2.6
This PR aligns the docs with the NJR-first execution contract already implemented in code.

### Follows Testing Standards
The added invariant test is deterministic, local-only, and does not depend on WebUI.

### Maintains Separation of Concerns
The PR is docs-plus-guard only. Runtime behavior remains unchanged.

## Dependencies

### External
- none

### Internal
- `src/cli.py`
- `src/pipeline/cli_njr_builder.py`
- `src/pipeline/executor.py`

## Timeline & Effort

| Task | Effort | Duration |
|------|--------|----------|
| docs rewrite | 0.25 day | same day |
| invariant test | 0.25 day | same day |
| verification | 0.25 day | same day |

**Total**: under 1 day

## Approval & Sign-Off

**Planner**: Codex
**Executor**: Codex
**Reviewer**: Rob

**Approval Status**: Approved and implemented

## Next Steps

1. Start `PR-CORE1-060` for remaining NJR-only migration work in queue/history.
2. Follow with controller legacy bridge cleanup in `PR-CTRL-061`.
3. Keep recommendation #1 closed and enforce it through the invariant test.

## Implementation Summary

**Implementation Date**: 2026-03-16
**Executor**: Codex
**Status**: COMPLETE

### What Was Implemented

#### 1. Recommendation closeout rewrite
`docs/StableNew_Revised_Top20_Recommendations.md` now treats recommendation #1 as implemented and updates the stale collect-only evidence for recommendation #5.

#### 2. Duplicate-path debt note rewrite
`docs/D-TECH-DEBT-001-Duplicate-Txt2Img-Paths.md` was rewritten from a discovery note into a current-state closeout audit.

#### 3. Invariant enforcement
A new pipeline test scans live source and active tests for the retired executor entrypoints and verifies the CLI still uses the canonical NJR path.

#### 4. Dead temp-harness removal
`tests/_tmp_test.py.skip` and `tests/gui/_tmp_test.py` were deleted.

### Files Created
1. `docs/PR_MAR26/PR-CLOSE-057-Recommendation-1-Closeout-and-Duplicate-Txt2Img-Audit.md`
2. `tests/pipeline/test_txt2img_path_closeout_invariants.py`

### Files Modified
1. `docs/StableNew_Revised_Top20_Recommendations.md`
2. `docs/D-TECH-DEBT-001-Duplicate-Txt2Img-Paths.md`

### Verification

```bash
pytest tests/pipeline/test_txt2img_path_closeout_invariants.py -q
pytest --collect-only -q
rg -n "run_full_pipeline\\(|_run_full_pipeline_impl\\(|def run_txt2img\\(|def _run_txt2img_impl\\(" src tests --glob '!tests/pipeline/test_txt2img_path_closeout_invariants.py'
```

The targeted test passed, collection stayed green, and the grep returned no live matches outside the invariant test itself.

### Tech Debt Addressed

- stale duplicate txt2img docs removed
- retired-path invariant added
- dead temp harnesses removed
