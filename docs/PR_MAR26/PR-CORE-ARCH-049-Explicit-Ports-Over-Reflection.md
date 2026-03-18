# PR-CORE-ARCH-049: Explicit Ports Over Reflection

**Status**: Specification
**Priority**: HIGH
**Effort**: LARGE
**Phase**: Architecture Stabilization
**Date**: 2026-03-11

## Context & Motivation

### Problem Statement
Active runtime code still uses reflection-style probing (`getattr`, attribute sniffing, optional handler discovery) in controller and GUI orchestration paths.

### Why This Matters
This weakens contracts, hides integration breakage until runtime, and conflicts with the explicit-controller-entrypoint standard documented in the canon.

### Current Architecture
Reflection remains common in:
- `src/gui/controllers/learning_controller.py`
- `src/gui/preview_panel_v2.py`
- `src/controller/job_service.py`
- related tests using loose doubles

### Reference
- `docs/StableNew_Coding_and_Testing_v2.6.md`
- `docs/D-ARCH-004-Codebase-Review-Top10-Issues-and-COAs.md`

## Goals & Non-Goals

### ✅ Goals
1. Replace reflection-heavy runtime wiring with explicit ports/contracts in high-risk paths.
2. Tighten test doubles to match those explicit contracts.
3. Keep low-risk data-model introspection out of scope unless directly necessary.

### ❌ Non-Goals
1. Do not remove every `getattr` in the repo.
2. Do not redesign the controller hierarchy.
3. Do not change queue/pipeline semantics.

## Allowed Files

### ✅ Files to Create
| File | Purpose | Lines (Est.) |
|------|---------|--------------|
| `src/controller/ports/*.py` | explicit runtime ports/protocols | 180 |
| `tests/controller/test_runtime_ports_contract.py` | contract tests for explicit ports | 160 |

### ✅ Files to Modify
| File | Reason | Lines Changed (Est.) |
|------|--------|----------------------|
| `src/gui/controllers/learning_controller.py` | replace reflection-heavy runtime probing in active paths | 180 |
| `src/gui/preview_panel_v2.py` | reduce optional attribute probing in active render path | 120 |
| `src/controller/job_service.py` | replace high-risk dynamic job/controller probing where explicit contracts are possible | 140 |
| related tests/doubles | align with explicit contracts | 140 |
| `docs/StableNew_Coding_and_Testing_v2.6.md` | codify permitted vs forbidden reflection patterns | 20 |

### ❌ Forbidden Files (DO NOT TOUCH)
| File/Directory | Reason |
|----------------|--------|
| `src/pipeline/job_builder_v2.py` | Not part of this cleanup |
| `src/pipeline/pipeline_runner.py` | Keep execution stable in this PR |
| `src/gui/main_window.py` | handled in PR-048 |

## Implementation Plan

### Step 1: Define explicit ports
Introduce narrow contracts for high-risk integrations such as:
- learning submission / queue-cap checks
- stage-card configuration access
- preview summary sources

### Step 2: Migrate active runtime paths
Replace reflection in the highest-risk runtime paths first, leaving benign introspection untouched.

### Step 3: Update tests
Replace loose attribute bags with explicit fakes implementing the new contracts.

## Testing Plan

### Unit Tests
- port contract tests

### Integration Tests
- controller and preview regressions

### Journey Tests
- golden path regression only

### Manual Testing
1. Exercise Learning plan build/run/recommendation flows.
2. Exercise preview panel and queue/history live updates.

## Verification Criteria

### ✅ Success Criteria
1. High-risk runtime paths no longer depend on optional handler discovery.
2. Test doubles align with explicit contracts.
3. Behavior remains unchanged.

### ❌ Failure Criteria
- reflection remains in the targeted high-risk paths
- contracts become broader/more coupled than the reflection they replace

## Risk Assessment

### Low Risk Areas
✅ Contract module creation

### Medium Risk Areas
⚠️ Updating tests and fakes
- **Mitigation**: migrate tests in the same PR

### High Risk Areas
❌ Runtime contract mistakes in orchestration paths
- **Mitigation**: keep interfaces narrow and add controller regression tests

### Rollback Plan
Revert to the previous reflection-based implementation for the targeted slice if a missed dependency surfaces.

## Tech Debt Analysis

## Tech Debt Removed
✅ Reduces hidden runtime coupling
✅ Aligns code with explicit API rules in the canon

## Tech Debt Added
⚠️ Additional protocol/port definitions

**Net Tech Debt**: -1

## Architecture Alignment

### ✅ Enforces Architecture v2.6
Moves runtime wiring toward explicit APIs and away from dynamic probing.

### ✅ Follows Testing Standards
Tests target explicit contracts rather than optional attributes.

### ✅ Maintains Separation of Concerns
Ports isolate orchestration expectations from concrete GUI/controller internals.

## Dependencies

### External
- none

### Internal
- controller, GUI preview, and learning modules

## Timeline & Effort

### Breakdown
| Task | Effort | Duration |
|------|--------|----------|
| contract design | 1 day | Day 1 |
| runtime migration | 2 days | Days 2-3 |
| tests and cleanup | 1 day | Day 4 |

**Total**: about 1 week

## Approval & Sign-Off

**Planner**: Codex
**Executor**: Codex
**Reviewer**: Rob

**Approval Status**: Pending

## Next Steps

1. Define narrow ports for the highest-risk reflection areas.
2. Migrate runtime paths and tests.
3. Reassess remaining reflection for later cleanup.
