# PR-CORE-LEARN-046: Rating Detail Analytics Integration

**Status**: Specification
**Priority**: MEDIUM
**Effort**: MEDIUM
**Phase**: Post-Learning Recovery Review
**Date**: 2026-03-11

## Context & Motivation

### Problem Statement
The Learning review flow now captures richer rating detail, including context flags and sub-scores, but the recommendation engine still reduces all evidence to `metadata.user_rating`. The system presents a nuanced scoring UI without using most of the additional data downstream.

### Why This Matters
This creates a trust gap. Users spend effort providing structured review context, but recommendations still behave like a flat-star system. It also limits the system’s ability to avoid misapplying anatomy-heavy or composition-heavy evidence to contexts where those categories do not apply.

### Current Architecture
Learning experiment ratings and review-tab feedback both write richer metadata into `LearningRecord.metadata`, including fields such as:
- `user_rating_raw`
- `rating_context`
- `rating_details`
- `subscores`

However, `RecommendationEngine._score_records(...)` currently ingests only `metadata.user_rating` and ignores the richer structure.

### Reference
- `src/learning/learning_record.py`
- `src/gui/controllers/learning_controller.py`
- `src/gui/views/learning_review_panel.py`
- `src/learning/recommendation_engine.py`
- `src/learning/rating_schema.py`

## Goals & Non-Goals

### ✅ Goals
1. Make the recommendation engine consume richer rating detail when present.
2. Preserve backward compatibility with older flat-rating records.
3. Use context flags and sub-score details conservatively so recommendations become more trustworthy without overfitting.
4. Keep `user_rating` as the canonical fallback aggregate for existing consumers.

### ❌ Non-Goals
1. Do not redesign the Learning record format completely in this PR.
2. Do not change the visible review UI beyond small explanatory text if needed.
3. Do not introduce ML/statistical modeling beyond deterministic weighting adjustments.
4. Do not migrate historical records destructively.

## Allowed Files

### ✅ Files to Create
| File | Purpose | Lines (Est.) |
|------|---------|--------------|
| `tests/learning_v2/test_recommendation_engine_rating_detail_integration.py` | Coverage for context/subscore-aware recommendation weighting | 180 |

### ✅ Files to Modify
| File | Reason | Lines Changed (Est.) |
|------|--------|----------------------|
| `src/learning/recommendation_engine.py` | Ingest and weight rating details/context safely | 120 |
| `src/learning/learning_record.py` | Add small helper accessors/normalization if needed, without schema breakage | 40 |
| `src/gui/controllers/learning_controller.py` | Ensure metadata fields written by Learning ratings remain normalized and consistent | 40 |
| `tests/learning_v2/test_recommendation_engine_guards.py` | Adjust or extend coverage for backward compatibility | 40 |
| `docs/Learning_System_Spec_v2.6.md` | Document how richer rating detail contributes to analytics | 30 |

### ❌ Forbidden Files (DO NOT TOUCH)
| File/Directory | Reason |
|----------------|--------|
| `src/pipeline/**` | No execution-path changes |
| `src/queue/**` | Not relevant |
| `src/gui/views/review_tab_frame_v2.py` | Review-tab UI is not the target here |
| `src/gui/views/learning_review_panel.py` except for minimal explanatory text if absolutely needed | UI redesign is not part of this PR |

## Implementation Plan

### Step 1: Normalize available rating detail
Add a small normalization layer for record metadata access so the engine can read:
- aggregate rating
- raw rating
- context flags
- sub-scores

This must tolerate:
- old records with only `user_rating`
- learning records with `rating_context` and `rating_details`
- review-tab feedback with `subscores`

**Modify**:
- `src/learning/recommendation_engine.py`
- optionally `src/learning/learning_record.py`

### Step 2: Introduce conservative context-aware weighting
Use context/subscore detail to refine evidence weighting, not to replace the aggregate score.

Examples:
- if a record’s context says no people, anatomy-heavy evidence should not strongly influence recommendations for people-heavy contexts
- if a relevant subscore is present and poor, confidence for associated parameter settings should be reduced
- if detail is absent, fall back to current aggregate behavior

Important:
- keep the logic deterministic and auditable
- do not create a black-box scoring system

**Modify**:
- `src/learning/recommendation_engine.py`

### Step 3: Keep record-writing consistent
Review the Learning rating-writing path to ensure metadata naming is internally consistent and the new ingestion layer has a stable contract.

**Modify**:
- `src/gui/controllers/learning_controller.py`

### Step 4: Add tests and docs
Add focused regression tests for:
- old flat-rating records
- new detailed learning ratings
- new detailed review-tab feedback
- mixed datasets

Update the Learning system doc so the analytics contract is explicit.

**Create**:
- `tests/learning_v2/test_recommendation_engine_rating_detail_integration.py`

**Modify**:
- `tests/learning_v2/test_recommendation_engine_guards.py`
- `docs/Learning_System_Spec_v2.6.md`

## Testing Plan

### Unit Tests
- metadata normalization for old vs new record shapes
- context-aware weighting behavior
- backward-compatibility fallback when details are absent

### Integration Tests
- targeted Learning recommendation flow if required by existing suite

### Journey Tests
- optional extension of Learning review-to-recommendation journey if current coverage is insufficient

### Manual Testing
1. Rate people-focused images with anatomy/composition sub-scores and confirm recommendations still appear.
2. Rate non-people images with people context disabled and confirm anatomy-specific evidence is not over-weighted.
3. Confirm older records without detail still produce recommendations.
4. Confirm the UI still shows recommendation rationale without requiring a schema migration.

## Verification Criteria

### ✅ Success Criteria
1. Recommendation scoring uses rating detail/context when present.
2. Older records remain valid and continue to contribute through aggregate fallback.
3. Recommendation behavior becomes more context-sensitive without suppressing all output.
4. Tests explicitly cover mixed old/new datasets.

### ❌ Failure Criteria
- older records stop contributing
- detailed records produce brittle or opaque recommendation behavior
- recommendation output becomes less stable or disappears unexpectedly

## Risk Assessment

### Low Risk Areas
✅ Backward-compatible metadata reads

### Medium Risk Areas
⚠️ Weighting design
- **Mitigation**: keep the aggregate rating as the base signal and apply small, deterministic adjustments only

### High Risk Areas
❌ Overfitting or opaque recommendation behavior
- **Mitigation**: document the weighting rules, keep them simple, and cover mixed evidence sets with tests

### Rollback Plan
Revert the rating-detail weighting logic while retaining the metadata fields and UI capture path.

## Tech Debt Analysis

## Tech Debt Removed
✅ Aligns analytics behavior with the richer rating schema already being captured
✅ Reduces semantic drift between UI review detail and downstream recommendation logic

## Tech Debt Added
⚠️ Slightly more complex scoring logic, justified by stronger schema alignment

**Net Tech Debt**: -1

## Architecture Alignment

### ✅ Enforces Architecture v2.6
This PR improves Learning analytics only and leaves the canonical execution pipeline unchanged.

### ✅ Follows Testing Standards
Adds explicit mixed-schema and backward-compatibility coverage.

### ✅ Maintains Separation of Concerns
Rating capture remains in controllers/UI; analytics interpretation remains in the recommendation engine.

## Dependencies

### External
- none

### Internal
- `src/learning/recommendation_engine.py`
- `src/learning/learning_record.py`
- `src/gui/controllers/learning_controller.py`
- `src/learning/rating_schema.py`

## Timeline & Effort

### Breakdown
| Task | Effort | Duration |
|------|--------|----------|
| Metadata normalization | 0.5 day | Day 1 |
| Context-aware weighting | 0.5 day | Day 1 |
| Tests + docs | 0.5 day | Day 2 |

**Total**: 1-2 days

## Approval & Sign-Off

**Planner**: Codex
**Executor**: Codex
**Reviewer**: Rob

**Approval Status**: Pending

## Next Steps

1. Implement the recommendation evidence-tier regression fix first.
2. Clean runtime/session artifacts from version control.
3. Integrate richer rating detail into analytics once the recommendation surface is stable again.
