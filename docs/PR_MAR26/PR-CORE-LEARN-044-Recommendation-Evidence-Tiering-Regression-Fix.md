# PR-CORE-LEARN-044: Recommendation Evidence Tiering Regression Fix

**Status**: Specification
**Priority**: HIGH
**Effort**: SMALL
**Phase**: Post-Learning Recovery Review
**Date**: 2026-03-11

## Context & Motivation

### Problem Statement
The current recommendation evidence-tiering logic suppresses all recommendations whenever there are 1-2 `learning_experiment_rating` records for a stage, even if substantial `review_tab_feedback` evidence exists for the same stage.

### Why This Matters
This is a behavioral regression. Users can move from "recommendations available" to "no recommendations shown" simply by starting to rate a new experiment. The system appears broken at the point where the user is actively providing more data.

### Current Architecture
`RecommendationEngine.recommend(...)` currently splits stage-scoped evidence into experiment ratings and review feedback, then hard-drops to an empty evidence set for sparse experiment data. The Learning review UI and automation logic consume that empty result as "no recommendations."

### Reference
- `src/learning/recommendation_engine.py`
- `src/gui/views/learning_review_panel.py`
- `src/gui/controllers/learning_controller.py`
- `docs/PR_MAR26/PR-GUI-LEARN-037-Analytics-and-Recommendation-Hardening.md`

## Goals & Non-Goals

### ✅ Goals
1. Remove the regression where sparse experiment data suppresses all recommendations.
2. Preserve the intended evidence hierarchy: controlled experiment evidence should remain higher trust than review feedback.
3. Distinguish recommendation source and confidence tier explicitly so the UI can present degraded-confidence recommendations safely.
4. Prevent low-confidence fallback evidence from being used for automatic pipeline application when experiment evidence is insufficient.

### ❌ Non-Goals
1. Do not redesign the full recommendation engine in this PR.
2. Do not change Learning record schema in this PR.
3. Do not alter queue or pipeline execution behavior.
4. Do not merge rating-detail analytics here; that belongs in a later follow-up PR.

## Allowed Files

### ✅ Files to Create
| File | Purpose | Lines (Est.) |
|------|---------|--------------|
| `tests/learning_v2/test_recommendation_engine_evidence_tiering.py` | Regression coverage for sparse experiment evidence behavior | 140 |

### ✅ Files to Modify
| File | Reason | Lines Changed (Est.) |
|------|--------|----------------------|
| `src/learning/recommendation_engine.py` | Fix evidence selection and expose recommendation evidence tier/source | 70 |
| `src/gui/controllers/learning_controller.py` | Respect low-confidence/manual-only recommendations for automation decisions | 30 |
| `src/gui/views/learning_review_panel.py` | Display recommendation source/tier clearly in the UI | 30 |
| `tests/learning_v2/test_apply_recommendations.py` | Ensure automation does not apply fallback/manual-only evidence | 40 |
| `tests/learning_v2/test_recommendation_engine_guards.py` | Update guard expectations for the new tiered fallback behavior | 50 |

### ❌ Forbidden Files (DO NOT TOUCH)
| File/Directory | Reason |
|----------------|--------|
| `src/pipeline/*` | This PR is analytics/UI-only and must not affect generation behavior |
| `src/queue/*` | No queue semantics are involved |
| `src/learning/learning_record.py` | Record-shape changes belong in PR-CORE-LEARN-046 |
| `src/gui/views/review_tab_frame_v2.py` | Review tab behavior is unrelated to this regression |

## Implementation Plan

### Step 1: Introduce explicit evidence-tier outcomes
Refactor `RecommendationEngine.recommend(...)` so it does not collapse sparse experiment evidence to `[]`.

Implement a deterministic tier policy:
- `experiment_strong`: `>= 3` experiment records, used for recommendations and eligible for automation
- `experiment_sparse_plus_review`: `1-2` experiment records plus any review feedback, recommendations allowed but flagged as manual-only
- `review_only`: no experiment records, review feedback allowed but flagged as manual-only
- `no_evidence`: empty

**Modify**:
- `src/learning/recommendation_engine.py`

### Step 2: Surface tier/source in recommendation payloads
Extend `RecommendationSet` and/or `ParameterRecommendation` UI output so the caller can distinguish:
- evidence source
- confidence tier
- automation eligibility

This must be additive and backward-compatible with existing tests and UI consumers.

**Modify**:
- `src/learning/recommendation_engine.py`

### Step 3: Gate automation on evidence trust
Update Learning automation behavior so only strong experiment-backed recommendations can be auto-applied. Lower-tier recommendations remain visible but suggestion-only.

**Modify**:
- `src/gui/controllers/learning_controller.py`
- `src/gui/views/learning_review_panel.py`

### Step 4: Add regression tests
Cover:
- sparse experiment evidence plus review evidence returns recommendations
- sparse experiment evidence alone returns recommendations only if policy says so, otherwise explicit no-evidence/manual-only state
- auto-apply remains blocked for fallback/manual-only tiers

**Create**:
- `tests/learning_v2/test_recommendation_engine_evidence_tiering.py`

**Modify**:
- `tests/learning_v2/test_recommendation_engine_guards.py`
- `tests/learning_v2/test_apply_recommendations.py`

## Testing Plan

### Unit Tests
- recommendation evidence tier selection
- recommendation payload source/tier fields

### Integration Tests
- none required beyond Learning controller automation tests

### Journey Tests
- optional targeted Learning review-to-recommendation flow if existing journey coverage needs adjustment

### Manual Testing
1. Seed review feedback without experiment ratings and confirm recommendations appear as lower-confidence/manual-only.
2. Add 1-2 experiment ratings and confirm recommendations do not disappear.
3. Confirm apply/auto-micro-experiment does not use fallback/manual-only recommendations.
4. Add 3+ experiment ratings and confirm the UI upgrades to experiment-backed recommendations.

## Verification Criteria

### ✅ Success Criteria
1. Recommendations no longer disappear when 1-2 experiment ratings exist.
2. Recommendation payloads expose evidence tier/source clearly.
3. Automation remains blocked for fallback/manual-only evidence.
4. Existing experiment-backed recommendation behavior remains intact.

### ❌ Failure Criteria
- sparse experiment evidence still returns an empty recommendation set when usable fallback evidence exists
- auto-apply can run on review-only evidence
- existing recommendation tests regress

## Risk Assessment

### Low Risk Areas
✅ Recommendation display text changes: additive and isolated

### Medium Risk Areas
⚠️ Automation gating
- **Mitigation**: treat anything not explicitly strong-experiment-backed as manual-only

### High Risk Areas
❌ Recommendation semantics drift
- **Mitigation**: encode evidence-tier behavior directly in tests rather than relying on implicit current behavior

### Rollback Plan
Revert recommendation tiering changes and restore the prior guard behavior in one PR-sized revert.

## Tech Debt Analysis

## Tech Debt Removed
✅ Eliminates an implicit and misleading "no recommendations" state caused by sparse experiment evidence
✅ Makes evidence trust explicit instead of hidden in control flow

## Tech Debt Added
⚠️ Minor payload expansion for recommendation metadata

**Net Tech Debt**: -1

## Architecture Alignment

### ✅ Enforces Architecture v2.6
This PR stays within Learning analytics/UI logic and does not alter the canonical execution pipeline.

### ✅ Follows Testing Standards
Adds focused regression coverage for the exact failure mode identified in review.

### ✅ Maintains Separation of Concerns
Evidence selection remains in the recommendation layer; automation merely consumes an explicit eligibility signal.

## Dependencies

### External
- none

### Internal
- `src/learning/recommendation_engine.py`
- `src/gui/controllers/learning_controller.py`
- `src/gui/views/learning_review_panel.py`

## Timeline & Effort

### Breakdown
| Task | Effort | Duration |
|------|--------|----------|
| Tier-policy refactor | 0.5 day | Day 1 |
| UI/automation wiring | 0.25 day | Day 1 |
| Regression tests | 0.25 day | Day 1 |

**Total**: 1 day

## Approval & Sign-Off

**Planner**: Codex
**Executor**: Codex
**Reviewer**: Rob

**Approval Status**: Pending

## Next Steps

1. Implement the evidence-tier regression fix.
2. Validate Learning recommendation behavior manually and via tests.
3. Continue with runtime artifact hygiene in PR-CLEANUP-LEARN-045.
