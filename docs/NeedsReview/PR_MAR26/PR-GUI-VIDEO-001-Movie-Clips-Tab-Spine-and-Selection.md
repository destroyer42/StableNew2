# PR-GUI-VIDEO-001: Movie Clips Tab Spine and Selection

**Status**: Specification
**Priority**: HIGH
**Effort**: SMALL
**Phase**: Video MVP
**Date**: 2026-03-11

## Context & Motivation

### Problem Statement
StableNew can generate and review still images, but there is no integrated UI for turning those images into short clips.

### Why This Matters
Users want a direct workflow for creating simple motion assets from existing outputs without leaving the app or manually invoking FFmpeg.

### Current Architecture
The existing pipeline stage model is image-centric. A new top-level tab is the safest place to add clip assembly without disturbing the canonical generation path.

### Reference
- `docs/D-VIDEO-002-Movie-Clips-Tab-MVP-Discovery.md`
- `src/pipeline/video.py`
- `docs/D-VIDEO-001-AnimateDiff-Integration-Discovery.md`

## Goals & Non-Goals

### Goals
1. Add a new top-level `Movie Clips` tab.
2. Support selecting clip sources from:
   - a run output directory
   - a manual list of images
3. Display ordered image lists and clip settings in a dark-mode UI.
4. Persist tab state and last-used clip settings.

### Non-Goals
1. No actual clip assembly logic in this PR.
2. No queue integration.
3. No AnimateDiff.
4. No pipeline stage changes.

## Allowed Files

### Files to Create
| File | Purpose | Lines (Est.) |
|------|---------|--------------|
| `src/gui/views/movie_clips_tab_frame_v2.py` | New Movie Clips tab UI | 350 |
| `src/gui/view_contracts/movie_clips_contract.py` | UI normalization helpers | 120 |
| `tests/gui_v2/test_movie_clips_tab_v2.py` | GUI regression coverage | 220 |

### Files to Modify
| File | Reason | Lines Changed (Est.) |
|------|--------|----------------------|
| `src/gui/main_window_v2.py` | Register new top-level tab | 40 |
| `src/gui/app_state_v2.py` | Persist tab state and settings | 60 |
| `src/gui/ui_tokens.py` | Reuse existing tokens if needed | 0-20 |

### Forbidden Files (DO NOT TOUCH)
| File/Directory | Reason |
|----------------|--------|
| `src/pipeline/pipeline_runner.py` | MVP tab spine must not alter runner semantics |
| `src/pipeline/stage_sequencer.py` | No stage changes in MVP |
| `src/pipeline/job_builder_v2.py` | No NJR changes in MVP |
| `src/controller/job_service.py` | No queue changes in this PR |

## Implementation Plan

### Step 1: Add tab shell
Create `MovieClipsTabFrameV2` with three zones:

- source selection
- ordered image list
- clip settings and action area

### Step 2: Add selection workflows
Support:

- browse for output folder
- load images from folder
- manual add/remove images
- deterministic sorting and reorder display

### Step 3: Persist UI state
Store:

- selected source mode
- last directory
- fps/codec/quality values
- selected images when re-openable

### Step 4: Add contract helpers
Normalize:

- source labels
- clip setting summaries
- image list ordering text

## Testing Plan

### Unit Tests
- contract formatting helpers

### Integration Tests
- none in this PR

### Journey Tests
- none in this PR

### Manual Testing
1. Open Movie Clips tab.
2. Select a run folder and confirm images load.
3. Add manual images and confirm ordering is stable.
4. Restart app and confirm settings restore.

## Verification Criteria

### Success Criteria
1. Movie Clips tab renders from `MainWindowV2`.
2. Users can select image sources without errors.
3. Settings restore correctly after restart.
4. No existing Pipeline, Review, or Learning flows regress.

### Failure Criteria
- any runner, queue, or pipeline stage behavior changes
- tab state does not restore
- image ordering is nondeterministic

## Risk Assessment

### Low Risk Areas
✅ New tab shell: isolated from pipeline execution

### Medium Risk Areas
⚠️ UI-state persistence
- **Mitigation**: use the same explicit restore/save pattern used by newer tabs

### High Risk Areas
❌ None if scope is held

### Rollback Plan
Revert the tab-registration commit and new tab files.

## Tech Debt Analysis

## Tech Debt Removed
✅ Creates a clean home for future clip functionality instead of hiding it in Review or Pipeline

## Tech Debt Added
⚠️ None expected

**Net Tech Debt**: -1

## Architecture Alignment

### Enforces Architecture v2.6
This PR keeps clip assembly outside the canonical generation stage chain.

### Follows Testing Standards
Adds focused GUI/contract tests only.

### Maintains Separation of Concerns
UI selection logic stays in the tab; no media assembly yet.

## Dependencies

### External
- none

### Internal
- `src/gui/main_window_v2.py`
- `src/gui/app_state_v2.py`
- `src/gui/widgets/*`

## Timeline & Effort

### Breakdown
| Task | Effort | Duration |
|------|--------|----------|
| Tab shell | 0.5 day | Day 1 |
| Source selection + persistence | 0.5 day | Day 1 |
| Tests | 0.5 day | Day 1 |

**Total**: 1-2 days

## Approval & Sign-Off

**Planner**: Codex
**Executor**: Codex
**Reviewer**: Rob

**Approval Status**: Pending

## Next Steps

1. Implement tab shell and persistence.
2. Add clip-build controller/service in PR-VIDEO-002.
3. Add journeys/docs in PR-VIDEO-003.

