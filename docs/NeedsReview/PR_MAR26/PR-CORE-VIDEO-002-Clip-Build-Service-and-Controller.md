# PR-CORE-VIDEO-002: Clip Build Service and Controller Wiring

**Status**: Specification
**Priority**: HIGH
**Effort**: MEDIUM
**Phase**: Video MVP
**Date**: 2026-03-11

## Context & Motivation

### Problem Statement
The UI alone is not enough; StableNew needs a clean service/controller path for turning selected images into clip artifacts and writing durable manifests.

### Why This Matters
Without a dedicated service layer, clip assembly will become GUI-owned logic and drift away from the repo’s controller/service boundaries.

### Current Architecture
`VideoCreator` already exists but is not integrated into a user-facing controller flow.

### Reference
- `docs/D-VIDEO-002-Movie-Clips-Tab-MVP-Discovery.md`
- `src/pipeline/video.py`
- `docs/PR_MAR26/PR-GUI-VIDEO-001-Movie-Clips-Tab-Spine-and-Selection.md`

## Goals & Non-Goals

### Goals
1. Introduce a dedicated clip-build service around `VideoCreator`.
2. Add controller entrypoints for the Movie Clips tab.
3. Write clip manifests and managed outputs.
4. Support both image-sequence and slideshow modes.

### Non-Goals
1. No queue-backed clip jobs in MVP.
2. No AnimateDiff.
3. No stage type additions.
4. No History/Preview deep integration beyond basic success surfacing.

## Allowed Files

### Files to Create
| File | Purpose | Lines (Est.) |
|------|---------|--------------|
| `src/video/movie_clip_models.py` | Clip request/result/manifest models | 160 |
| `src/video/movie_clip_service.py` | Wrap `VideoCreator` with app-facing semantics | 240 |
| `tests/video/test_movie_clip_service.py` | Service tests | 220 |

### Files to Modify
| File | Reason | Lines Changed (Est.) |
|------|--------|----------------------|
| `src/controller/app_controller.py` | Add Movie Clips entrypoints | 80 |
| `src/pipeline/video.py` | Small hardening if needed for ordering/error reporting | 40 |
| `src/gui/views/movie_clips_tab_frame_v2.py` | Wire actions to controller | 120 |
| `tests/gui_v2/test_movie_clips_tab_v2.py` | Controller-action regression tests | 120 |

### Forbidden Files (DO NOT TOUCH)
| File/Directory | Reason |
|----------------|--------|
| `src/pipeline/stage_models.py` | No pipeline stage changes |
| `src/pipeline/stage_sequencer.py` | No canonical stage-order changes |
| `src/pipeline/pipeline_runner.py` | Clip MVP must remain post-processing |
| `src/queue/` | No queue wiring in MVP |

## Implementation Plan

### Step 1: Define clip data models
Add:

- clip request
- clip settings
- clip result
- clip manifest payload

### Step 2: Implement service layer
Service responsibilities:

- validate selected images
- normalize ordering
- create managed output folder
- call `VideoCreator`
- write manifest JSON

### Step 3: Wire controller API
Add explicit `AppController` entrypoints, for example:

- `on_build_movie_clip(...)`
- `on_load_movie_clip_source(...)`

### Step 4: Wire tab actions
Tab must:

- show build progress/status
- surface output path
- surface failure reason

## Testing Plan

### Unit Tests
- clip manifest round-trip
- ordering normalization
- slideshow/image-sequence mode validation

### Integration Tests
- mocked FFmpeg success/failure cases

### Journey Tests
- none in this PR

### Manual Testing
1. Build a clip from a run folder.
2. Build a clip from manually selected files.
3. Confirm output and manifest are written.
4. Confirm invalid file sets fail with clear error.

## Verification Criteria

### Success Criteria
1. Movie Clips tab can build a clip end-to-end.
2. Clip manifests are written deterministically.
3. Failures do not crash the app.
4. No queue/runner/pipeline behavior changes.

### Failure Criteria
- GUI performs direct FFmpeg orchestration itself
- output ordering is unstable
- failed builds leave half-written manifests without clear status

## Risk Assessment

### Low Risk Areas
✅ Reusing `VideoCreator`

### Medium Risk Areas
⚠️ Mixed file ordering and file validation
- **Mitigation**: centralize all ordering/validation in the service

⚠️ FFmpeg availability
- **Mitigation**: validate availability up front and return actionable status

### High Risk Areas
❌ None if clip assembly remains out of the pipeline stage chain

### Rollback Plan
Revert service/controller wiring and keep the tab shell only.

## Tech Debt Analysis

## Tech Debt Removed
✅ Prevents clip logic from leaking into GUI callbacks

## Tech Debt Added
⚠️ None expected

**Net Tech Debt**: -1

## Architecture Alignment

### Enforces Architecture v2.6
This PR treats clips as post-execution artifacts, not alternate generation jobs.

### Follows Testing Standards
Adds focused unit and GUI regression coverage.

### Maintains Separation of Concerns
Controller/service own clip assembly; tab owns selection and status display.

## Dependencies

### External
- `ffmpeg` on PATH

### Internal
- `src/pipeline/video.py`
- `src/controller/app_controller.py`
- `src/gui/views/movie_clips_tab_frame_v2.py`

## Timeline & Effort

### Breakdown
| Task | Effort | Duration |
|------|--------|----------|
| Data models + service | 1 day | Day 2 |
| Controller + tab wiring | 0.5 day | Day 2 |
| Tests | 0.5 day | Day 3 |

**Total**: 2-3 days

## Approval & Sign-Off

**Planner**: Codex
**Executor**: Codex
**Reviewer**: Rob

**Approval Status**: Pending

## Next Steps

1. Implement service/controller path.
2. Add journey coverage and docs in PR-VIDEO-003.
3. Optionally plan later queue-backed clip builds as a separate post-MVP PR.

