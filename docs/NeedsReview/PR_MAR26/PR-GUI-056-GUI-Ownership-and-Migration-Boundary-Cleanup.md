# PR-GUI-056: GUI Ownership and Migration Boundary Cleanup

**Status**: Specification
**Priority**: MEDIUM
**Effort**: MEDIUM
**Phase**: GUI Architecture Cleanup
**Date**: 2026-03-11

## Context & Motivation

### Problem Statement
GUI ownership boundaries are unclear across `src/gui`, `src/gui_v2`, legacy tests, and migration-prep work.

### Why This Matters
Unclear ownership creates placement drift, slows migration planning, and makes it harder to distinguish active GUI runtime from adapters, shims, and transitional code.

### Current Architecture
Most active Tk V2 runtime code still lives under `src/gui`, while `src/gui_v2` contains a much smaller adapter-oriented surface. Legacy and migration-prep code coexist with active runtime code.

### Reference
- `src/gui/`
- `src/gui_v2/`
- `src/gui/main_window.py`
- `src/gui/main_window_v2.py`
- `docs/D-ARCH-004-Codebase-Review-Top10-Issues-and-COAs.md`

## Goals & Non-Goals

### ✅ Goals
1. Define clear ownership rules for `src/gui` vs `src/gui_v2`.
2. Freeze placement rules for new GUI code.
3. Move only the highest-value ambiguous files or document why they stay.
4. Align tests/docs with the clarified ownership model.

### ❌ Non-Goals
1. Do not mass-move every GUI file in one PR.
2. Do not perform the PySide6 migration here.
3. Do not redesign GUI runtime behavior.

## Allowed Files

### ✅ Files to Create
| File | Purpose | Lines (Est.) |
|------|---------|--------------|
| `docs/Subsystems/GUI/GUI_Ownership_Map_v2.6.md` | ownership rules and placement guidance | 120 |

### ✅ Files to Modify
| File | Reason | Lines Changed (Est.) |
|------|--------|----------------------|
| `docs/DOCS_INDEX_v2.6.md` | index GUI ownership map if active | 10 |
| `docs/ARCHITECTURE_v2.6.md` | clarify GUI ownership/boundary language if needed | 20 |
| selected GUI/test files with highest ambiguity | move or relabel only if doing so clearly improves ownership | 120 |
| `tests/TEST_SURFACE_MANIFEST.md` | align test ownership references if relevant | 10 |

### ❌ Forbidden Files (DO NOT TOUCH)
| File/Directory | Reason |
|----------------|--------|
| `src/pipeline/**` | Out of scope |
| `src/queue/**` | Out of scope |
| large-scale GUI runtime rewrites | This PR is boundary cleanup only |

## Implementation Plan

### Step 1: Define GUI ownership map
Classify:
- active Tk runtime
- toolkit-agnostic adapters/contracts
- migration-prep scaffolding
- legacy/compatibility surfaces

### Step 2: Freeze placement rules
Document where new files must go for each category.

### Step 3: Move only high-value ambiguous files
If a small number of files are clearly misplaced and low-risk to move, relocate them. Otherwise document and defer.

### Step 4: Align tests/docs
Update references so contributors can follow the ownership model consistently.

## Testing Plan

### Unit Tests
- none required unless a file move affects imports

### Integration Tests
- GUI smoke tests if import paths move

### Journey Tests
- none beyond smoke if no runtime behavior changes

### Manual Testing
1. Confirm GUI imports still resolve cleanly.
2. Confirm contributors can determine where new GUI code belongs from the ownership map alone.

## Verification Criteria

### ✅ Success Criteria
1. GUI ownership rules are explicit.
2. New code placement has a documented answer.
3. Highest-value ambiguity is reduced without noisy mass moves.

### ❌ Failure Criteria
- the repo still has no clear answer for where active GUI code belongs
- large file moves create churn without real boundary improvement

## Risk Assessment

### Low Risk Areas
✅ Ownership-map documentation

### Medium Risk Areas
⚠️ Limited file moves
- **Mitigation**: move only where the ownership win is obvious

### High Risk Areas
❌ Broad path churn
- **Mitigation**: no mass moves in this PR

### Rollback Plan
Revert any moved files and keep the ownership map/documentation if path moves prove too disruptive.

## Tech Debt Analysis

## Tech Debt Removed
✅ Reduces GUI placement ambiguity
✅ Supports future migration planning with clearer boundaries

## Tech Debt Added
⚠️ None expected if moves stay minimal

**Net Tech Debt**: -1

## Architecture Alignment

### ✅ Enforces Architecture v2.6
Clarifies subsystem boundaries without altering execution semantics.

### ✅ Follows Testing Standards
Requires smoke validation if imports move.

### ✅ Maintains Separation of Concerns
Keeps boundary clarification separate from runtime feature work.

## Dependencies

### External
- none

### Internal
- GUI runtime folders
- GUI tests
- architecture/docs index

## Timeline & Effort

### Breakdown
| Task | Effort | Duration |
|------|--------|----------|
| ownership map | 0.5 day | Day 1 |
| boundary cleanup decisions | 0.5 day | Day 1 |
| limited moves/docs/test import fixes | 0.5-1 day | Day 2 |

**Total**: 1-2 days

## Approval & Sign-Off

**Planner**: Codex
**Executor**: Codex
**Reviewer**: Rob

**Approval Status**: Pending

## Next Steps

1. Define and publish the GUI ownership map.
2. Freeze placement rules for new GUI work.
3. Move only the highest-value ambiguous files if warranted.
