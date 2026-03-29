# PR-CORE-LEARN-042: Discovered Review Evidence Tiering and Analytics

**Status**: Specification
**Priority**: HIGH
**Effort**: MEDIUM
**Phase**: Learning Recovery / Historical Review
**Date**: 2026-03-11

## Context & Motivation

### Problem Statement
Discovered-review group ratings are valuable, but they are weaker evidence than controlled Learning experiments. The system needs to capture them without corrupting recommendation quality.

### Why This Matters
If uncontrolled historical groups are treated the same as designed sweeps, recommendations will become less trustworthy.

### Current Architecture
The current recommendation engine already separates `learning_experiment_rating` from `review_tab_feedback`. This PR extends that evidence model with a third class.

### Reference
- `docs/D-LEARN-003-Auto-Discovered-Review-Experiments.md`
- `src/learning/recommendation_engine.py`
- `docs/Subsystems/Learning/Learning_System_Spec_v2.6.md`

## Goals & Non-Goals

### Goals
1. Add a distinct `record_kind` for discovered-review ratings.
2. Persist per-item discovered-review records with rich metadata.
3. Make analytics aware of discovered-review evidence.
4. Keep direct automated recommendations protected from noisy discovered evidence initially.

### Non-Goals
1. No attempt to fully merge discovered-review evidence with controlled experiment evidence.
2. No new recommendation UI ambitions beyond rationale/analytics support.

## Allowed Files

### Files to Modify
| File | Reason | Lines Changed (Est.) |
|------|--------|----------------------|
| `src/gui/controllers/learning_controller.py` | Write discovered-review records | 120 |
| `src/learning/learning_record.py` | Support any needed helper accessors | 40 |
| `src/learning/recommendation_engine.py` | Add evidence-tier handling | 120 |
| `tests/learning_v2/test_recommendation_engine_guards.py` | Extend guard coverage | 100 |
| `tests/controller/test_learning_controller_review_feedback.py` | Persist discovered-review record tests | 100 |

### Files to Create
| File | Purpose | Lines (Est.) |
|------|---------|--------------|
| `tests/integration/test_discovered_review_learning_analytics_e2e.py` | End-to-end evidence-tier integration | 220 |

### Forbidden Files (DO NOT TOUCH)
| File/Directory | Reason |
|----------------|--------|
| `src/pipeline/*` | No pipeline changes |
| `src/gui/views/experiment_design_panel.py` | No designed experiment UI changes |

## Implementation Plan

### Step 1: Add record kind
Use:

- `output_discovery_review`

Persist metadata including:

- discovered group id
- stage
- prompt hash
- varying fields
- artifact path
- rating and sub-scores

### Step 2: Add evidence-tier logic
Recommendation engine policy:

- `learning_experiment_rating`: high-trust evidence
- `output_discovery_review`: supplemental analytics evidence only in phase 1
- `review_tab_feedback`: fallback feedback evidence

### Step 3: Add analytics summaries
Enable analytics surfaces to report discovered-review evidence counts and parameter tendencies without directly auto-applying recommendations from it.

## Testing Plan

### Unit Tests
- discovered-review records are persisted with correct kind
- recommendation engine does not over-trust discovered evidence

### Integration Tests
- end-to-end discovered-review rating to analytics visibility

### Journey Tests
- covered in PR-043

### Manual Testing
1. Rate a discovered group.
2. Confirm records are written.
3. Confirm recommendations do not suddenly overreact to discovered-only evidence.

## Verification Criteria

### Success Criteria
1. Discovered-review ratings are persisted separately.
2. Analytics can see them.
3. Recommendation automation remains conservative.

### Failure Criteria
- discovered-review evidence is treated as controlled experiment evidence on day one

## Risk Assessment

### Low Risk Areas
✅ Record-kind extension

### Medium Risk Areas
⚠️ Recommendation evidence policy
- **Mitigation**: default to conservative exclusion from auto-recommendation

### High Risk Areas
❌ Recommendation drift from uncontrolled evidence
- **Mitigation**: explicit tests for non-use in recommendation automation

### Rollback Plan
Keep record persistence but disable discovered-review recommendation participation.

## Tech Debt Analysis

## Tech Debt Removed
✅ Prevents silent evidence pollution

## Tech Debt Added
⚠️ Adds another record kind, justified by evidence quality differences

**Net Tech Debt**: 0

## Architecture Alignment

### Enforces Architecture v2.6
Strengthens Learning evidence semantics without touching generation paths.

### Follows Testing Standards
Adds unit and integration coverage for evidence-tier behavior.

### Maintains Separation of Concerns
Controller writes records; recommendation engine interprets them conservatively.

## Dependencies

### External
- none

### Internal
- Learning controller
- learning record writer
- recommendation engine

## Timeline & Effort

### Breakdown
| Task | Effort | Duration |
|------|--------|----------|
| Record-kind persistence | 0.5 day | Day 5 |
| Recommendation guard logic | 0.5 day | Day 5 |
| Tests | 0.5 day | Day 5 |

**Total**: 1-2 days

## Approval & Sign-Off

**Planner**: Codex
**Executor**: Codex
**Reviewer**: Rob

**Approval Status**: Pending

## Next Steps

1. Implement evidence-tier handling.
2. Lock journeys/docs/cleanup in PR-043.

