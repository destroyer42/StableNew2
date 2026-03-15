# PR-GUI-LEARN-039: Discovered Review Experiment Models and Store

**Status**: Specification
**Priority**: HIGH
**Effort**: MEDIUM
**Phase**: Learning Recovery / Historical Review
**Date**: 2026-03-11

## Context & Motivation

### Problem Statement
StableNew has no durable model for imported or auto-discovered historical comparison groups. Existing Learning persistence is aimed at designed experiments, not arbitrary groups inferred from prior outputs.

### Why This Matters
Without a dedicated data model and store, output-scan results will either remain ephemeral or be forced awkwardly into the designed Learning experiment schema.

### Current Architecture
`LearningExperimentStore` already provides durable workspace semantics for designed experiments. This PR introduces a sibling store for discovered-review experiments without changing queue or runner behavior.

### Reference
- `docs/D-LEARN-003-Auto-Discovered-Review-Experiments.md`
- `docs/Learning_System_Spec_v2.6.md`

## Goals & Non-Goals

### Goals
1. Introduce a durable discovered-review experiment model.
2. Add status lifecycle support: `waiting_review`, `in_review`, `closed`, `ignored`.
3. Add a scan-index model for incremental output scanning.
4. Keep this separate from designed Learning experiment definitions.

### Non-Goals
1. No output scanning yet.
2. No Learning tab UI yet.
3. No recommendation-engine changes yet.
4. No queue or pipeline changes.

## Allowed Files

### Files to Create
| File | Purpose | Lines (Est.) |
|------|---------|--------------|
| `src/learning/discovered_review_models.py` | Data models for discovered groups/items/index entries | 220 |
| `src/learning/discovered_review_store.py` | Durable store for discovered groups and scan index | 260 |
| `tests/learning_v2/test_discovered_review_store.py` | Store round-trip coverage | 220 |

### Files to Modify
| File | Reason | Lines Changed (Est.) |
|------|--------|----------------------|
| `docs/Learning_System_Spec_v2.6.md` | Add discovered-review group semantics | 40 |
| `docs/DOCS_INDEX_v2.6.md` | Index discovery/PR docs if needed | 20 |

### Forbidden Files (DO NOT TOUCH)
| File/Directory | Reason |
|----------------|--------|
| `src/gui/views/*` | No UI in this PR |
| `src/gui/controllers/learning_controller.py` | No controller integration yet |
| `src/pipeline/*` | No pipeline behavior changes |
| `src/queue/*` | No queue changes |

## Implementation Plan

### Step 1: Add discovered-review data models
Create models for:

- `DiscoveredReviewExperiment`
- `DiscoveredReviewItem`
- `DiscoveredReviewHandle`
- `OutputScanIndexEntry`

### Step 2: Add store layer
Persist under:

- `data/learning/discovered_experiments/{group_id}/meta.json`
- `data/learning/discovered_experiments/{group_id}/items.json`
- `data/learning/discovered_experiments/{group_id}/review_state.json`
- `data/learning/discovered_experiments/scan_index.json`

### Step 3: Add lifecycle helpers
Store must support:

- create/update group
- list handles by status
- close/ignore/reopen group
- update per-item review state

## Testing Plan

### Unit Tests
- group and item round-trip
- status lifecycle transitions
- scan index read/write
- deterministic listing order

### Integration Tests
- none in this PR

### Journey Tests
- none in this PR

### Manual Testing
1. Create a discovered group fixture.
2. Persist and reload it.
3. Change status and confirm it persists.

## Verification Criteria

### Success Criteria
1. Discovered-review groups persist independently of designed Learning experiments.
2. Status lifecycle is durable and deterministic.
3. Scan index can track processed artifacts.

### Failure Criteria
- discovered groups are stored by overloading `LearningExperiment`
- no explicit status lifecycle exists

## Risk Assessment

### Low Risk Areas
✅ Pure persistence/model layer

### Medium Risk Areas
⚠️ Store duplication relative to `experiment_store.py`
- **Mitigation**: keep structure parallel and naming explicit rather than merging incompatible models prematurely

### High Risk Areas
❌ None if scope is held

### Rollback Plan
Revert the new store/models and doc adjustments.

## Tech Debt Analysis

## Tech Debt Removed
✅ Prevents misuse of the designed experiment model for uncontrolled history groups

## Tech Debt Added
⚠️ Introduces a second Learning-adjacent store, justified by different lifecycle semantics

**Net Tech Debt**: 0

## Architecture Alignment

### Enforces Architecture v2.6
This PR stays entirely in the Learning post-execution domain.

### Follows Testing Standards
Adds focused store/model tests.

### Maintains Separation of Concerns
Persistence is introduced before scanning or UI.

## Dependencies

### External
- none

### Internal
- `src/learning/experiment_store.py` as structural reference only

## Timeline & Effort

### Breakdown
| Task | Effort | Duration |
|------|--------|----------|
| Models | 0.5 day | Day 1 |
| Store | 0.5 day | Day 1 |
| Tests + docs | 0.5 day | Day 1 |

**Total**: 1-2 days

## Approval & Sign-Off

**Planner**: Codex
**Executor**: Codex
**Reviewer**: Rob

**Approval Status**: Pending

## Next Steps

1. Implement store/models.
2. Build scanner/grouping engine in PR-040.

