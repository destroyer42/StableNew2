# PR-GUI-LEARN-037: Analytics and Recommendation Hardening

**Status**: Implemented
**Priority**: MEDIUM
**Effort**: MEDIUM
**Phase**: Learning Recovery
**Date**: 2026-03-10

## Context & Motivation
Recommendations depended on weakly structured records and could not be trusted until record semantics were cleaned up.

## Goals
1. Normalize experiment-vs-review record ingestion.
2. Improve confidence gating.
3. Prevent sparse or noisy data from generating misleading recommendations.

## Allowed Files
- `src/learning/recommendation_engine.py`
- `src/gui/controllers/learning_controller.py`
- related recommendation tests

## Implementation Summary
1. `RecommendationEngine` now filters records by explicit `record_kind`.
2. Stage-scoped recommendation evidence is separated into experiment ratings and review-tab feedback.
3. Sparse experiment evidence is suppressed instead of falling through to noisy review feedback.
4. Review-tab feedback remains usable only when experiment evidence is absent.

## Validation
- `tests/learning_v2/test_recommendation_engine_guards.py`
- `tests/learning_v2/test_apply_recommendations.py`

