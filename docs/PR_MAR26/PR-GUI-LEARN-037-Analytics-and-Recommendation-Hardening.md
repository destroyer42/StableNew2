# PR-GUI-LEARN-037: Analytics and Recommendation Hardening

**Status**: 🟡 Specification
**Priority**: MEDIUM
**Effort**: MEDIUM
**Phase**: Learning Recovery
**Date**: 2026-03-10

## Context & Motivation
Recommendations currently depend on weakly structured records and cannot be trusted until record semantics are cleaned up.

## Goals
1. Normalize experiment-vs-review record ingestion.
2. Improve confidence gating and rationale display.
3. Prevent sparse/noisy data from generating misleading recommendations.

## Allowed Files
- `src/learning/recommendation_engine.py`
- `src/learning/learning_record.py`
- `src/gui/controllers/learning_controller.py`
- analytics/recommendation GUI tests

## Implementation Plan
1. Add explicit record-kind/type handling.
2. Harden scoring and evidence thresholds.
3. Improve recommendation display rationale.

## Testing Plan
- valid recommendations from experiment data
- graceful no-recommendation on sparse data
- review feedback segregation tests

## Next Steps
Execute after PR-036.
