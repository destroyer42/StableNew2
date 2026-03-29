# PR-CORE-LEARN-055: Learning Analytics Contract Reconciliation

**Status**: Specification
**Priority**: HIGH
**Effort**: MEDIUM
**Phase**: Learning Stabilization
**Date**: 2026-03-11

## Context & Motivation

### Problem Statement
The Learning subsystem captures richer rating data than the recommendation layer currently uses, and the current evidence policy creates dead zones where users receive no useful recommendation guidance.

### Why This Matters
This weakens trust in Learning. Users provide more detail than the system uses, and recommendation availability/confidence is not aligned cleanly with the evidence model.

### Current Architecture
Learning records may contain:
- aggregate ratings
- raw ratings
- context flags
- sub-scores
- experiment-vs-review record kinds

But recommendation behavior still relies heavily on aggregate score and rigid evidence guards.

### Reference
- `src/learning/recommendation_engine.py`
- `src/learning/learning_record.py`
- `src/gui/controllers/learning_controller.py`
- `src/gui/views/learning_review_panel.py`
- `docs/Subsystems/Learning/Learning_System_Spec_v2.6.md`
- `docs/D-ARCH-004-Codebase-Review-Top10-Issues-and-COAs.md`

## Goals & Non-Goals

### ✅ Goals
1. Reconcile Learning record capture and recommendation consumption contracts.
2. Make recommendation evidence tiers explicit.
3. Use richer rating detail conservatively where present.
4. Preserve backward compatibility with existing records.

### ❌ Non-Goals
1. Do not rewrite the recommendation engine from scratch.
2. Do not redesign the Learning review UI in this PR.
3. Do not introduce opaque scoring logic.

## Allowed Files

### ✅ Files to Create
| File | Purpose | Lines (Est.) |
|------|---------|--------------|
| `tests/learning_v2/test_learning_analytics_contract.py` | mixed-record analytics contract coverage | 180 |

### ✅ Files to Modify
| File | Reason | Lines Changed (Est.) |
|------|--------|----------------------|
| `src/learning/recommendation_engine.py` | explicit evidence tiers and richer metadata ingestion | 140 |
| `src/learning/learning_record.py` | normalization helpers if needed | 40 |
| `src/gui/controllers/learning_controller.py` | ensure stable metadata naming for analytics inputs | 40 |
| `docs/Subsystems/Learning/Learning_System_Spec_v2.6.md` | clarify recommendation evidence and rating-detail rules | 30 |
| `tests/learning_v2/test_recommendation_engine_guards.py` | update guard expectations | 60 |

### ❌ Forbidden Files (DO NOT TOUCH)
| File/Directory | Reason |
|----------------|--------|
| `src/pipeline/**` | No execution changes |
| `src/queue/**` | No queue changes |
| `src/gui/views/review_tab_frame_v2.py` | Review-tab UI is not part of this reconciliation |

## Implementation Plan

### Step 1: Define the analytics contract explicitly
Document and encode:
- supported record kinds
- evidence tiers
- automation eligibility rules
- fallback behavior for older flat records

### Step 2: Reconcile recommendation evidence policy
Ensure recommendation availability, confidence, and automation eligibility are explicit and do not create opaque dead zones.

### Step 3: Integrate richer rating detail conservatively
Use context/sub-score detail only as a controlled refinement over aggregate rating, never as an opaque replacement.

### Step 4: Add mixed-schema tests
Cover:
- old flat records
- new structured records
- mixed experiment/review evidence

## Testing Plan

### Unit Tests
- analytics contract tests
- mixed evidence tier tests
- backward-compatibility tests

### Integration Tests
- focused Learning recommendation flow if needed

### Journey Tests
- optional extension of review-to-recommendation journey

### Manual Testing
1. Use old and new rating records and confirm recommendations still appear sensibly.
2. Confirm recommendation source/confidence behavior is understandable.
3. Confirm auto-apply rules only use sufficiently strong evidence.

## Verification Criteria

### ✅ Success Criteria
1. Recommendation evidence tiers are explicit and test-covered.
2. Richer rating detail is used when present without breaking older records.
3. Recommendation behavior becomes more explainable and less brittle.

### ❌ Failure Criteria
- older records stop contributing
- recommendation behavior becomes less predictable
- analytics logic becomes opaque or under-tested

## Risk Assessment

### Low Risk Areas
✅ Metadata normalization helpers

### Medium Risk Areas
⚠️ Recommendation policy changes
- **Mitigation**: keep rules explicit, deterministic, and test-covered

### High Risk Areas
❌ Overfitting or overcomplicating scoring logic
- **Mitigation**: keep aggregate rating as the backbone and use detail only for conservative refinement

### Rollback Plan
Revert the evidence-policy/detail-ingestion changes while retaining captured metadata fields.

## Tech Debt Analysis

## Tech Debt Removed
✅ Aligns recommendation behavior with captured Learning data
✅ Reduces semantic drift between review capture and analytics

## Tech Debt Added
⚠️ Slightly more analytics policy complexity

**Net Tech Debt**: -1

## Architecture Alignment

### ✅ Enforces Architecture v2.6
Learning remains post-execution and does not create alternate run paths.

### ✅ Follows Testing Standards
Adds explicit mixed-schema analytics coverage.

### ✅ Maintains Separation of Concerns
Record capture, record schema, and recommendation logic remain in their proper layers.

## Dependencies

### External
- none

### Internal
- Learning record and recommendation modules

## Timeline & Effort

### Breakdown
| Task | Effort | Duration |
|------|--------|----------|
| contract definition | 0.5 day | Day 1 |
| recommendation reconciliation | 1 day | Day 1-2 |
| tests and docs | 0.5 day | Day 2 |

**Total**: 1-2 days

## Approval & Sign-Off

**Planner**: Codex
**Executor**: Codex
**Reviewer**: Rob

**Approval Status**: Pending

## Next Steps

1. Define explicit analytics and evidence-tier rules.
2. Update the engine and tests.
3. Reassess recommendation UX after the contract is stabilized.
