# PR-CORE-054: Workspace Path Abstraction and Runtime Boundary

**Status**: Specification
**Priority**: HIGH
**Effort**: MEDIUM
**Phase**: Persistence and Environment Cleanup
**Date**: 2026-03-11

## Context & Motivation

### Problem Statement
Runtime persistence is coupled to the repository working tree through hardcoded local paths for learning sessions, photo assets, and state.

### Why This Matters
This mixes source, fixtures, and runtime artifacts, increases repo pollution risk, and makes alternate workspace layouts harder to support.

### Current Architecture
Examples:
- `src/learning/learning_paths.py`
- `data/learning/experiments`
- `data/photo_optimize/assets`
- `state/*.json`

### Reference
- `src/learning/learning_paths.py`
- `docs/Learning_System_Spec_v2.6.md`
- `docs/D-ARCH-004-Codebase-Review-Top10-Issues-and-COAs.md`
- `docs/PR_MAR26/PR-CLEANUP-LEARN-045-Runtime-Artifact-Version-Control-Hygiene.md`

## Goals & Non-Goals

### ✅ Goals
1. Introduce a centralized workspace-path abstraction for runtime data roots.
2. Preserve current default behavior initially.
3. Enable a future external workspace override without rewriting every caller.
4. Separate fixture policy from runtime persistence policy.

### ❌ Non-Goals
1. Do not move all runtime data outside the repo in this PR.
2. Do not redesign every persistence store.
3. Do not combine VCS hygiene cleanup into the same implementation PR unless strictly mechanical.

## Allowed Files

### ✅ Files to Create
| File | Purpose | Lines (Est.) |
|------|---------|--------------|
| `src/state/workspace_paths.py` | centralized runtime path resolver | 160 |
| `tests/state/test_workspace_paths.py` | path-resolution contract tests | 120 |

### ✅ Files to Modify
| File | Reason | Lines Changed (Est.) |
|------|--------|----------------------|
| `src/learning/learning_paths.py` | delegate to centralized workspace paths | 40 |
| `src/photo_optimize/store.py` | consume centralized workspace roots | 40 |
| `src/gui/main_window_v2.py` | use centralized UI-state/workspace path helpers if applicable | 30 |
| `docs/StableNew_Coding_and_Testing_v2.6.md` | document runtime-vs-fixture boundary | 20 |
| `docs/Learning_System_Spec_v2.6.md` | clarify workspace-root behavior | 20 |

### ❌ Forbidden Files (DO NOT TOUCH)
| File/Directory | Reason |
|----------------|--------|
| `src/pipeline/**` | No execution changes |
| `src/queue/**` | No queue changes |
| `.github/workflows/**` | Out of scope |

## Implementation Plan

### Step 1: Add centralized runtime path resolver
Create one module that resolves:
- repo-default workspace root
- optional override root
- child roots for learning, photo optimize, UI state, and related runtime data

### Step 2: Migrate persistence callers
Update learning/photo-optimize/state callers to use the new path resolver.

### Step 3: Preserve current defaults
Keep current repo-root defaults so behavior does not regress during the abstraction step.

### Step 4: Document boundary rules
Document that runtime data is resolved through workspace paths and is distinct from versioned fixtures.

## Testing Plan

### Unit Tests
- workspace path resolution
- override handling
- default-path backward compatibility

### Integration Tests
- focused persistence smoke tests if needed

### Journey Tests
- none required beyond regression suite

### Manual Testing
1. Start app with default settings and confirm persistence still works.
2. If override support is included, point it at an alternate workspace and confirm the app uses it.

## Verification Criteria

### ✅ Success Criteria
1. Runtime path resolution is centralized.
2. Current default behavior remains intact.
3. Future workspace relocation becomes a configuration change instead of a codebase-wide edit.

### ❌ Failure Criteria
- persistence callers still hardcode runtime roots widely
- existing local persistence paths break unexpectedly

## Risk Assessment

### Low Risk Areas
✅ Adding a central path resolver

### Medium Risk Areas
⚠️ Touching multiple persistence callers
- **Mitigation**: keep behavior identical and add contract tests

### High Risk Areas
❌ Silent path migration bugs
- **Mitigation**: default-to-current behavior and verify by smoke tests

### Rollback Plan
Revert callers to direct paths and remove the abstraction module if migration introduces instability.

## Tech Debt Analysis

## Tech Debt Removed
✅ Reduces hardcoded runtime-root sprawl
✅ Prepares for cleaner workspace separation

## Tech Debt Added
⚠️ One more infrastructure module to maintain

**Net Tech Debt**: -1

## Architecture Alignment

### ✅ Enforces Architecture v2.6
Preserves runtime behavior while clarifying persistence boundaries.

### ✅ Follows Testing Standards
Adds explicit path-resolution contract coverage.

### ✅ Maintains Separation of Concerns
Path policy becomes infrastructure, not scattered persistence logic.

## Dependencies

### External
- none

### Internal
- learning persistence
- photo optimize persistence
- UI state persistence

## Timeline & Effort

### Breakdown
| Task | Effort | Duration |
|------|--------|----------|
| path service design | 0.5 day | Day 1 |
| caller migration | 1 day | Day 1-2 |
| tests and docs | 0.5 day | Day 2 |

**Total**: 1-2 days

## Approval & Sign-Off

**Planner**: Codex
**Executor**: Codex
**Reviewer**: Rob

**Approval Status**: Pending

## Next Steps

1. Introduce centralized runtime path resolution.
2. Migrate persistence callers.
3. Pair with runtime-artifact hygiene cleanup after the abstraction is in place.
