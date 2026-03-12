# PR-CORE-ARCH-047: Core Seam Extraction and Module Caps

**Status**: Specification
**Priority**: HIGH
**Effort**: LARGE
**Phase**: Architecture Stabilization
**Date**: 2026-03-11

## Context & Motivation

### Problem Statement
Critical modules in controller, pipeline, and GUI layers are oversized and multi-purpose, making safe change difficult.

### Why This Matters
Large files are hiding multiple responsibilities, increasing regression risk and slowing review, testing, and future migration work.

### Current Architecture
Examples of oversized active files:
- `src/controller/app_controller.py`
- `src/pipeline/executor.py`
- `src/pipeline/pipeline_runner.py`
- `src/gui/controllers/learning_controller.py`
- `src/gui/main_window_v2.py`

### Reference
- `docs/D-ARCH-004-Codebase-Review-Top10-Issues-and-COAs.md`
- `docs/StableNew_Coding_and_Testing_v2.6.md`

## Goals & Non-Goals

### ✅ Goals
1. Extract behavior-preserving seams from oversized active modules.
2. Move cohesive logic into service/helper modules with explicit responsibilities.
3. Add contract tests around extracted seams before major internal movement.
4. Establish a practical module-size policy for critical runtime files.

### ❌ Non-Goals
1. Do not redesign execution architecture.
2. Do not change business behavior in this PR.
3. Do not mix GUI migration or folder moves into this PR.

## Allowed Files

### ✅ Files to Create
| File | Purpose | Lines (Est.) |
|------|---------|--------------|
| `src/controller/app_controller_services/*.py` | Extracted controller helper services | 300 |
| `src/learning/learning_controller_services/*.py` | Learning-controller helper services | 250 |
| `tests/controller/test_app_controller_service_contracts.py` | Contract coverage for extracted seams | 160 |
| `tests/learning_v2/test_learning_controller_service_contracts.py` | Learning seam coverage | 160 |

### ✅ Files to Modify
| File | Reason | Lines Changed (Est.) |
|------|--------|----------------------|
| `src/controller/app_controller.py` | Delegate extracted responsibilities | 250 |
| `src/gui/controllers/learning_controller.py` | Delegate extracted responsibilities | 250 |
| `src/pipeline/executor.py` | Extract helper sections only if behavior-preserving and directly covered | 150 |
| `docs/StableNew_Coding_and_Testing_v2.6.md` | Document module-cap/seam policy | 25 |

### ❌ Forbidden Files (DO NOT TOUCH)
| File/Directory | Reason |
|----------------|--------|
| `src/pipeline/job_builder_v2.py` | Not part of this structural refactor |
| `src/queue/**` | Keep queue semantics stable |
| `src/gui/main_window.py` | Legacy shim handled in PR-048 |

## Implementation Plan

### Step 1: Define extraction seams
Identify cohesive responsibility clusters in `AppController` and `LearningController`, such as:
- recommendation orchestration
- experiment persistence orchestration
- photo optimize orchestration
- UI state sync helpers

### Step 2: Extract behavior-preserving service modules
Move logic into helper/service modules with typed inputs/outputs and no hidden GUI dependencies.

### Step 3: Replace inline logic with delegation
Reduce the parent files by delegating to the new seams while preserving public controller APIs.

### Step 4: Add seam-level regression tests
Add contract tests that lock behavior before further decomposition continues.

## Testing Plan

### Unit Tests
- seam service behavior tests

### Integration Tests
- controller behavior regression tests for touched flows

### Journey Tests
- golden path regression only

### Manual Testing
1. Run key Learning, Review, and Photo Optomize actions.
2. Confirm no controller entrypoints changed externally.

## Verification Criteria

### ✅ Success Criteria
1. Extracted logic has explicit modules and tests.
2. Parent files shrink materially without behavior change.
3. Golden Path continues to pass.

### ❌ Failure Criteria
- behavior changes are bundled with structural extraction
- new seams still depend on hidden GUI state

## Risk Assessment

### Low Risk Areas
✅ Helper/service extraction with tests

### Medium Risk Areas
⚠️ Controller wiring changes
- **Mitigation**: preserve public methods and add focused regression coverage

### High Risk Areas
❌ Partial extraction leaving duplicated logic
- **Mitigation**: each extracted responsibility must have one owner by PR end

### Rollback Plan
Revert the seam extraction PR and restore in-file logic from a single commit boundary.

## Tech Debt Analysis

## Tech Debt Removed
✅ Reduces oversized-module pressure
✅ Creates stable seams for later refactors

## Tech Debt Added
⚠️ Temporary delegation layering during extraction

**Net Tech Debt**: -1

## Architecture Alignment

### ✅ Enforces Architecture v2.6
No architecture changes; only responsibility cleanup.

### ✅ Follows Testing Standards
Requires contract tests for extracted seams.

### ✅ Maintains Separation of Concerns
Moves orchestration helpers out of god modules into explicit services.

## Dependencies

### External
- none

### Internal
- `src/controller/app_controller.py`
- `src/gui/controllers/learning_controller.py`
- related tests

## Timeline & Effort

### Breakdown
| Task | Effort | Duration |
|------|--------|----------|
| seam identification | 1 day | Day 1 |
| extraction + delegation | 2-3 days | Days 2-4 |
| tests and cleanup | 1 day | Day 5 |

**Total**: 1 week

## Approval & Sign-Off

**Planner**: Codex
**Executor**: Codex
**Reviewer**: Rob

**Approval Status**: Pending

## Next Steps

1. Implement seam extraction in one controller slice at a time.
2. Continue with reflection cleanup in PR-049.
3. Revisit module caps after first extractions land.
