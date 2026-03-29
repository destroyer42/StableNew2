# PR-TEST-LEARN-043: Discovered Review Journeys and Documentation

**Status**: Specification
**Priority**: MEDIUM
**Effort**: MEDIUM
**Phase**: Learning Recovery / Historical Review
**Date**: 2026-03-11

## Context & Motivation

### Problem Statement
The discovered-review feature will touch scanning, persistence, Learning UI, and analytics. It needs end-to-end verification and canonical docs to avoid drift.

### Why This Matters
Without journey coverage, regressions in scan eligibility, status lifecycle, or review persistence will be hard to catch.

### Current Architecture
This feature spans Learning post-execution behavior only, but it crosses multiple modules and therefore needs explicit documentation and journeys.

### Reference
- `docs/D-LEARN-003-Auto-Discovered-Review-Experiments.md`
- `docs/Subsystems/Learning/Learning_System_Spec_v2.6.md`

## Goals & Non-Goals

### Goals
1. Add journey coverage for discovered-review workflow.
2. Add or update canonical docs describing:
   - scan criteria
   - group status lifecycle
   - evidence-tier semantics
3. Remove or clarify any obsolete learning docs that conflict.

### Non-Goals
1. No feature expansion.
2. No pipeline/queue changes.

## Allowed Files

### Files to Create
| File | Purpose | Lines (Est.) |
|------|---------|--------------|
| `tests/journeys/test_discovered_review_workflow.py` | End-to-end discovered-review journey | 260 |
| `docs/Discovered_Review_Workflow_v2.6.md` | Canonical feature workflow doc | 220 |

### Files to Modify
| File | Reason | Lines Changed (Est.) |
|------|--------|----------------------|
| `docs/Subsystems/Learning/Learning_System_Spec_v2.6.md` | Final discovered-review semantics | 40 |
| `docs/DOCS_INDEX_v2.6.md` | Index new workflow doc | 20 |
| `tests/integration/test_golden_path_suite_v2_6.py` | Add or classify discovered-review smoke if appropriate | 40 |

### Forbidden Files (DO NOT TOUCH)
| File/Directory | Reason |
|----------------|--------|
| `src/pipeline/*` | No pipeline changes |
| `src/queue/*` | No queue changes |

## Implementation Plan

### Step 1: Add end-to-end journey
Cover:

1. historical outputs scanned
2. eligible group created
3. group appears in Learning inbox
4. ratings saved
5. group closed

### Step 2: Add canonical workflow docs
Document:

- eligibility rules
- scan timing
- lifecycle states
- evidence-tier behavior

### Step 3: Cleanup conflicting docs
Clarify or supersede any ambiguous notes implying that only designed experiments can contribute to Learning review surfaces.

## Testing Plan

### Unit Tests
- none beyond earlier PRs

### Integration Tests
- discovered-review analytics flow

### Journey Tests
- full discovered-review workflow

### Manual Testing
1. Start app on a real populated output tree.
2. Confirm discovered groups appear.
3. Review and close one group.
4. Restart app and confirm closed state persists.

## Verification Criteria

### Success Criteria
1. Journey test passes reliably.
2. Docs accurately match implementation.
3. Closed/ignored groups persist across restart.

### Failure Criteria
- journey depends on non-deterministic output ordering
- docs contradict actual grouping rules

## Risk Assessment

### Low Risk Areas
✅ Documentation updates

### Medium Risk Areas
⚠️ Journey determinism with filesystem fixtures
- **Mitigation**: use fixture output trees with deterministic manifests

### High Risk Areas
❌ None if earlier PRs are stable

### Rollback Plan
Revert journey/docs updates separately if they prove unstable.

## Tech Debt Analysis

## Tech Debt Removed
✅ Prevents the feature from becoming another undocumented Learning side-path

## Tech Debt Added
⚠️ None expected

**Net Tech Debt**: -1

## Architecture Alignment

### Enforces Architecture v2.6
Documents and validates the feature strictly as post-execution Learning behavior.

### Follows Testing Standards
Adds journey and canonical documentation coverage.

### Maintains Separation of Concerns
Validation and docs land after feature semantics are stable.

## Dependencies

### External
- none

### Internal
- PR-039 through PR-042

## Timeline & Effort

### Breakdown
| Task | Effort | Duration |
|------|--------|----------|
| Journey tests | 0.5 day | Day 6 |
| Docs | 0.5 day | Day 6 |
| Cleanup | 0.5 day | Day 6 |

**Total**: 1-2 days

## Approval & Sign-Off

**Planner**: Codex
**Executor**: Codex
**Reviewer**: Rob

**Approval Status**: Pending

## Next Steps

1. Execute PRs in order.
2. Re-evaluate whether discovered-review evidence should later be promoted into higher-trust recommendation inputs.

