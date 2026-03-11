# PR-GUI-LEARN-031: Learning Workspace Persistence Foundation

**Status**: 🟡 Specification
**Priority**: CRITICAL
**Effort**: MEDIUM
**Phase**: Learning Recovery
**Date**: 2026-03-10

## Context & Motivation

### Problem Statement
Learning session persistence is currently stored as a UI blob inside `ui_state.json`. It is not a real experiment/session system, is not explicitly user-addressable, and does not reliably survive shutdown/restart.

### Why This Matters
Users lose experiment definitions, partial review progress, and selected variants/images. This breaks the core learning workflow.

### Current Architecture
`LearningTabFrame` calls `LearningController.export_resume_state()` and writes that payload into `UIStateStore`. `MainWindowV2` restores it on startup. No dedicated experiment store exists.

### Reference
- `src/gui/views/learning_tab_frame_v2.py`
- `src/gui/controllers/learning_controller.py`
- `src/gui/learning_state.py`

## Goals & Non-Goals

### ✅ Goals
1. Add a dedicated learning experiment store under `data/learning/experiments/`.
2. Add explicit `Save`, `Save As`, `Load`, and `Resume Last` actions in the Learning tab.
3. Persist experiment definition plus resumable session state separately from generic UI state.
4. Keep backward-compatible restore from the legacy embedded UI payload.

### ❌ Non-Goals
1. No multi-variable support in this PR.
2. No analytics/recommendation logic changes in this PR.
3. No stage execution model rewrite in this PR.

## Allowed Files

### ✅ Files to Create
| File | Purpose | Lines (Est.) |
|------|---------|--------------|
| `src/learning/experiment_store.py` | Durable experiment/session persistence | 220 |
| `tests/learning_v2/test_experiment_store.py` | Store round-trip coverage | 180 |

### ✅ Files to Modify
| File | Reason | Lines Changed (Est.) |
|------|--------|----------------------|
| `src/learning/learning_paths.py` | Add canonical experiment workspace paths | 40 |
| `src/gui/views/learning_tab_frame_v2.py` | Add save/load/resume UI and store integration | 220 |
| `src/gui/controllers/learning_controller.py` | Export/import session payload helpers | 120 |
| `src/gui/learning_state.py` | Harden serializable session state | 80 |
| `src/gui/main_window_v2.py` | Restore via experiment pointer instead of raw blob only | 40 |
| `tests/gui_v2/test_learning_tab_state_persistence.py` | Update persistence expectations | 120 |
| `tests/controller/test_learning_controller_resume_state.py` | Preserve controller round-trip coverage | 40 |
| `docs/DOCS_INDEX_v2.6.md` | Index new learning persistence docs if needed | 10 |

### ❌ Forbidden Files (DO NOT TOUCH)
| File/Directory | Reason |
|----------------|--------|
| `src/queue/` | Out of scope |
| `src/pipeline/pipeline_runner.py` | Out of scope |
| `src/pipeline/executor.py` | Out of scope |

## Implementation Plan

### Step 1: Add a dedicated experiment store
Create a small persistence layer for:
- `session.json`
- experiment metadata/index
- last-opened experiment id

### Step 2: Integrate the Learning tab with the store
Add header actions:
- `Save`
- `Save As`
- `Load`
- `Resume Last`

### Step 3: Preserve backward compatibility
If no experiment file exists, still accept the legacy `learning.session` UI payload and migrate it into the store on next save.

### Step 4: Reduce UI state usage
Persist only:
- `last_experiment_id`
- enablement/automation UI flags

## Testing Plan

### Unit Tests
- experiment id creation
- save/load session round-trip
- last-experiment pointer behavior

### Integration Tests
- Learning tab save then reload from disk
- legacy UI-state payload restore still works

### Manual Testing
1. Create experiment, save, close app, reopen, resume last.
2. Use `Save As`, verify separate experiment directory is created.
3. Load a previous session.json and verify plan/review selection restores.

## Verification Criteria

### ✅ Success Criteria
1. Experiments can be explicitly saved and loaded.
2. Resume after restart uses experiment files, not only UI state.
3. No current Learning persistence tests regress.

## Risk Assessment

### Medium Risk Areas
⚠️ `LearningState` serialization
- **Mitigation**: store only indices/ids, never live object identity

### Rollback Plan
Revert the experiment store integration and fall back to legacy UI-state persistence.

## Tech Debt Analysis
✅ Removes implicit “session blob in UI state” design debt.
⚠️ Leaves stage-model debt for later PRs.

## Architecture Alignment
### ✅ Maintains Separation of Concerns
Persistence moves into `src/learning/`, not `MainWindowV2`.

## Approval & Sign-Off
**Planner**: ChatGPT/Codex
**Executor**: Codex
**Reviewer**: Rob

## Next Steps
1. Execute this PR first.
2. Then implement stage capability contracts.
