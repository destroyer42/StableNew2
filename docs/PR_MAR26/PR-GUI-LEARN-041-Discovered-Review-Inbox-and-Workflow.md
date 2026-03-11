# PR-GUI-LEARN-041: Discovered Review Inbox and Workflow

**Status**: Specification
**Priority**: HIGH
**Effort**: LARGE
**Phase**: Learning Recovery / Historical Review
**Date**: 2026-03-11

## Context & Motivation

### Problem Statement
Once discovered-review groups exist, users need a coherent way to find them, review them, rate them, and close them.

### Why This Matters
Without a dedicated inbox/review flow, the scanner would create data with no practical user payoff.

### Current Architecture
The Learning tab already owns experiment design and review workflows. This PR extends the Learning tab to add a discovered-review mode instead of creating a disconnected new review tool.

### Reference
- `docs/D-LEARN-003-Auto-Discovered-Review-Experiments.md`
- `docs/PR_MAR26/PR-GUI-LEARN-039-Discovered-Review-Experiment-Models-and-Store.md`
- `docs/PR_MAR26/PR-CORE-LEARN-040-Output-Scanner-and-Grouping-Engine.md`

## Goals & Non-Goals

### Goals
1. Add a `Discovered Review Inbox` inside the Learning tab.
2. Show discovered groups by status.
3. Allow opening a discovered group into a review workflow.
4. Allow per-image rating and notes.
5. Allow closing or ignoring a group.
6. Trigger background scan at runtime and manual rescan from UI.

### Non-Goals
1. No recommendation-engine ingestion yet.
2. No attempt to force discovered groups into the current designed-experiment plan table.
3. No queue or pipeline changes.

## Allowed Files

### Files to Create
| File | Purpose | Lines (Est.) |
|------|---------|--------------|
| `src/gui/views/discovered_review_inbox_panel.py` | Inbox list/status UI | 280 |
| `src/gui/views/discovered_review_table.py` | Group item comparison table | 220 |
| `tests/gui_v2/test_discovered_review_inbox.py` | UI regressions | 260 |

### Files to Modify
| File | Reason | Lines Changed (Est.) |
|------|--------|----------------------|
| `src/gui/views/learning_tab_frame_v2.py` | Add discovered-review mode/panel integration | 180 |
| `src/gui/controllers/learning_controller.py` | Add discovered-review load/status/rating orchestration | 220 |
| `src/gui/views/learning_review_panel.py` | Reuse rating UI for discovered items where appropriate | 80 |
| `src/gui/learning_state.py` | Add selected discovered-group state if needed | 60 |

### Forbidden Files (DO NOT TOUCH)
| File/Directory | Reason |
|----------------|--------|
| `src/pipeline/*` | No pipeline changes |
| `src/queue/*` | No queue changes |
| `src/controller/job_service.py` | No queue job changes |

## Implementation Plan

### Step 1: Add inbox panel
Show:

- waiting_review groups
- in_review groups
- closed/ignored filters
- summary of inferred varying knobs

### Step 2: Add discovered review table
Each item row should show:

- image preview/name
- compact config summary
- varying fields
- current rating status

### Step 3: Add controller orchestration
Controller responsibilities:

- trigger async scan
- refresh inbox
- load selected group
- persist rating state
- close/ignore/reopen groups

### Step 4: Integrate with shared review panel
Reuse the current rating UI where possible, but keep discovered-group navigation separate from designed experiment plan semantics.

## Testing Plan

### Unit Tests
- controller state transitions for discovered-group lifecycle

### Integration Tests
- load discovered group and persist ratings/status changes

### Journey Tests
- covered in PR-043

### Manual Testing
1. Launch app and let scan finish.
2. Open Learning tab inbox.
3. Review a discovered group.
4. Rate all items.
5. Close group and confirm it leaves waiting-review state.

## Verification Criteria

### Success Criteria
1. Discovered groups are visible in Learning inbox.
2. Ratings persist per item.
3. Group status transitions persist.
4. Runtime scan does not freeze the UI.

### Failure Criteria
- discovered groups are forced through designed-experiment UI assumptions
- scanning blocks startup or tab interaction

## Risk Assessment

### Low Risk Areas
✅ Inbox rendering with stored handles

### Medium Risk Areas
⚠️ Learning tab complexity
- **Mitigation**: add discovered-review panels, not more conditional clutter in the existing form

⚠️ Async scan lifecycle
- **Mitigation**: debounce startup scan and update UI via existing dispatcher patterns

### High Risk Areas
❌ UI overload and workflow confusion
- **Mitigation**: separate `Designed Experiments` and `Discovered Review Inbox` clearly

### Rollback Plan
Disable inbox integration while keeping scanner/store code intact.

## Tech Debt Analysis

## Tech Debt Removed
✅ Gives historical outputs a first-class Learning review surface instead of leaving them stranded in folders

## Tech Debt Added
⚠️ Learning tab becomes broader in scope; offset by panel separation and explicit workflow labels

**Net Tech Debt**: 0

## Architecture Alignment

### Enforces Architecture v2.6
Extends post-execution Learning behavior only.

### Follows Testing Standards
Adds GUI/controller regression coverage.

### Maintains Separation of Concerns
Scanner/store remain backend logic; GUI consumes handles and controller entrypoints only.

## Dependencies

### External
- none

### Internal
- discovered-review store
- output scanner/grouping engine
- existing Learning review panel

## Timeline & Effort

### Breakdown
| Task | Effort | Duration |
|------|--------|----------|
| Inbox UI | 1 day | Day 4 |
| Controller integration | 1 day | Day 4 |
| Review-table/rating integration | 1 day | Day 5 |

**Total**: 2-3 days

## Approval & Sign-Off

**Planner**: Codex
**Executor**: Codex
**Reviewer**: Rob

**Approval Status**: Pending

## Next Steps

1. Implement inbox and review workflow.
2. Add evidence-tiered analytics in PR-042.

