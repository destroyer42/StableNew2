# PR-GUI-LEARN-032: Stage Capability Contract and Honest Experiment Model

**Status**: 🟡 Specification
**Priority**: CRITICAL
**Effort**: LARGE
**Phase**: Learning Recovery
**Date**: 2026-03-10

## Context & Motivation
The Learning UI advertises `txt2img`, `img2img`, and `upscale`, but the controller still builds a `txt2img`-centric execution path. This PR makes the stage model honest and explicit.

## Goals & Non-Goals
### ✅ Goals
1. Add stage capability metadata and input requirements.
2. Make Learning execution build the correct stage chain per experiment stage.
3. Add stage-specific input-image requirements for `img2img`, `adetailer`, and `upscale`.

### ❌ Non-Goals
1. No multi-variable combinations yet.
2. No analytics overhaul yet.

## Allowed Files
### ✅ Files to Create
- `src/learning/stage_capabilities.py`
- `src/learning/learning_job_builder.py`

### ✅ Files to Modify
- `src/gui/controllers/learning_controller.py`
- `src/gui/views/experiment_design_panel.py`
- `src/learning/variable_metadata.py`
- learning stage tests under `tests/learning_v2/`

### ❌ Forbidden Files
- runner/executor core

## Implementation Plan
1. Define stage capability metadata and required inputs.
2. Extract job construction out of `LearningController` into a builder.
3. Make the experiment form require base-image selection when stage demands it.
4. Reject invalid stage/input combinations before queue submission.

## Testing Plan
- unit tests for stage capability resolution
- controller tests for valid/invalid stage submissions
- UI tests for stage-dependent controls

## Key Risks
- current tests assume `txt2img` defaults
- stage-chain construction is currently controller-coupled

## Mitigation
- preserve `txt2img` behavior while adding explicit stage-specific builders

## Next Steps
Execute after PR-031.
