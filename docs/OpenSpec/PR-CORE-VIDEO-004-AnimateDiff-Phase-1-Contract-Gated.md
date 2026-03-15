# PR-CORE-VIDEO-004: AnimateDiff Phase 1 Contract-Gated Runtime Foundation

**Status**: Specification  
**Priority**: HIGH  
**Effort**: MEDIUM  
**Phase**: Video Phase 1  
**Date**: 2026-03-13

## Context & Motivation

### Problem Statement

StableNew can currently:

1. generate still images through the canonical PromptPack -> Builder -> NJR ->
   Queue -> Runner path
2. assemble existing images into clips through Movie Clips post-processing

It cannot yet:

1. take a prompt and a motion module
2. invoke AnimateDiff through WebUI
3. produce a canonical MP4 clip artifact through the NJR runtime path

### Why This Matters

Users asking for Sora-like or image-to-video behavior need a real motion
generation path, not only FFmpeg clip assembly.

Phase 1 creates the runtime substrate needed for that work without yet changing
the GUI or learning subsystems.

### Current Architecture

The current runtime path is:

PromptPack -> Builder Pipeline -> NormalizedJobRecord -> Queue -> Runner ->
Outputs + History -> Learning

Phase 1 must preserve that path and add AnimateDiff as a stage in NJR/runtime
terms, even though the underlying WebUI extension is expressed as an
`alwayson_scripts` modifier.

### Reference

1. [`docs/D-VIDEO-004-AnimateDiff-Current-State-Discovery.md`](../D-VIDEO-004-AnimateDiff-Current-State-Discovery.md)
2. [`docs/D-VIDEO-003-AnimateDiff-Research-Scaffold.md`](../D-VIDEO-003-AnimateDiff-Research-Scaffold.md)
3. [`docs/ARCHITECTURE_v2.6.md`](../ARCHITECTURE_v2.6.md)
4. AnimateDiff extension repo:
   https://github.com/continue-revolution/sd-webui-animatediff
5. AnimateDiff feature docs:
   https://github.com/continue-revolution/sd-webui-animatediff/blob/master/docs/features/README.md

## Goals & Non-Goals

### Goals

1. Add a capability-gated `animatediff` stage to the runtime type system.
2. Detect AnimateDiff availability through the WebUI scripts contract before
   execution.
3. Build AnimateDiff `txt2img` / `img2img` payloads through
   `alwayson_scripts["AnimateDiff"]`.
4. Produce deterministic output artifacts:
   - frame directory
   - MP4 clip
   - stage metadata
5. Keep execution NJR-only and queue/runner aligned with v2.6.

### Non-Goals

1. No GUI stage cards, tabs, or preset UI changes.
2. No learning-system support.
3. No Deforum, audio, ControlNet, or interpolation backends.
4. No history panel playback UI.
5. No architecture shortcuts that bypass Queue/Runner.

## Allowed Files

### Files to Create

| File | Purpose | Lines (Est.) |
|------|---------|--------------|
| `src/pipeline/animatediff_models.py` | Typed AnimateDiff config and result helpers | 120 |
| `tests/pipeline/test_animatediff_models.py` | Model/payload unit tests | 120 |
| `tests/pipeline/test_animatediff_runtime.py` | Sequencer/runner/executor tests | 220 |

### Files to Modify

| File | Reason | Lines Changed (Est.) |
|------|--------|----------------------|
| `src/api/client.py` | Add script-capability and motion-module discovery helpers | 120 |
| `src/pipeline/stage_models.py` | Add `ANIMATEDIFF` stage type | 20 |
| `src/pipeline/job_models_v2.py` | Allow/display `animatediff` stage labels | 40 |
| `src/pipeline/stage_sequencer.py` | Validate and order `animatediff` | 80 |
| `src/pipeline/run_plan.py` | Preserve `animatediff` in run plans | 40 |
| `src/pipeline/prompt_pack_job_builder.py` | Build `animatediff` stage from merged config when enabled | 120 |
| `src/pipeline/reprocess_builder.py` | Support reprocess jobs that end in `animatediff` | 60 |
| `src/pipeline/executor.py` | Implement AnimateDiff execution and frame handling | 220 |
| `src/pipeline/pipeline_runner.py` | Dispatch `animatediff` and persist runtime metadata | 180 |
| `src/pipeline/video.py` | Add frame-assembly helper usable by AnimateDiff runtime | 80 |
| `tests/pipeline/test_stage_sequencer_plan_builder.py` | Extend coverage for stage ordering | 40 |
| `tests/pipeline/test_pipeline_runner.py` | Extend dispatch/result coverage | 40 |

### Forbidden Files (DO NOT TOUCH)

| File/Directory | Reason |
|----------------|--------|
| `src/controller/` | Not required for runtime-only Phase 1 |
| `src/gui/` | GUI is Phase 2 work |
| `src/gui_v2/` | GUI is Phase 2 work |
| `src/learning/` | Learning is Phase 3 work |
| `src/queue/` | No queue architecture change is required |
| `src/history/` | Runtime metadata only; no history model/UI work in Phase 1 |

## Implementation Plan

### Step 1: Add AnimateDiff Stage Types And Typed Models

Add `StageType.ANIMATEDIFF` and the corresponding display text in the NJR
presentation helpers.

Create `src/pipeline/animatediff_models.py` with:

1. `AnimateDiffConfig`
2. `AnimateDiffCapability`
3. payload builder helpers
4. result normalization helpers

This file must be typed and must not import GUI modules.

**Create**: `src/pipeline/animatediff_models.py`  
**Modify**: `src/pipeline/stage_models.py`, `src/pipeline/job_models_v2.py`

### Step 2: Add WebUI Capability Detection

Extend `SDWebUIClient` with helpers that:

1. fetch `/sdapi/v1/scripts`
2. detect presence of `AnimateDiff`
3. best-effort extract motion-module names from the script metadata
4. return a typed capability result

If the extension is missing, execution must fail with a clear typed runtime
reason before attempting generation.

**Modify**: `src/api/client.py`

### Step 3: Extend Sequencing, RunPlan, And Builders

Update sequencing/builders so `animatediff` can exist in `stage_chain`.

Required rules:

1. `animatediff` requires a preceding image-producing stage
2. `animatediff` must be final in Phase 1
3. disabled `animatediff` stages are ignored like any other disabled stage

Prompt-pack and reprocess builders must be able to emit the stage from config.

**Modify**:
`src/pipeline/stage_sequencer.py`,
`src/pipeline/run_plan.py`,
`src/pipeline/prompt_pack_job_builder.py`,
`src/pipeline/reprocess_builder.py`

### Step 4: Implement AnimateDiff Execution

In `src/pipeline/executor.py`, implement a runtime helper that:

1. validates AnimateDiff capability
2. derives execution mode:
   - `txt2img` when generating from prompt
   - `img2img` when animating the previous stage output
3. builds the A1111 payload with `alwayson_scripts["AnimateDiff"]`
4. collects returned or saved frames
5. assembles MP4 through `VideoCreator`
6. returns typed metadata including:
   - `video_path`
   - `frame_paths`
   - `frame_count`
   - `fps`
   - `motion_module`
   - `extension_contract`

The implementation must use the existing `SDWebUIClient.txt2img(payload)` /
`img2img(payload)` methods instead of inventing new HTTP paths.

**Modify**: `src/pipeline/executor.py`, `src/pipeline/video.py`

### Step 5: Wire Runner Dispatch And Runtime Metadata

Add an `animatediff` branch in `PipelineRunner.run_njr()` that:

1. dispatches the new stage
2. threads the output artifact path into result metadata
3. keeps normal failure/cancellation behavior

Do not change the queue path. Do not add a direct controller shortcut.

**Modify**: `src/pipeline/pipeline_runner.py`

### Step 6: Add Deterministic Tests

Add tests for:

1. stage type and label registration
2. capability detection parsing
3. stage ordering and validation
4. runner dispatch
5. executor payload construction
6. MP4 assembly helper behavior with mocked client responses

Tests must not require a live AnimateDiff installation.

**Create**:
`tests/pipeline/test_animatediff_models.py`,
`tests/pipeline/test_animatediff_runtime.py`

**Modify**:
`tests/pipeline/test_stage_sequencer_plan_builder.py`,
`tests/pipeline/test_pipeline_runner.py`

## Testing Plan

### Unit Tests

1. `pytest tests/pipeline/test_animatediff_models.py -q`
2. `pytest tests/pipeline/test_stage_sequencer_plan_builder.py -q`
3. `pytest tests/pipeline/test_pipeline_runner.py -q`

### Integration Tests

1. `pytest tests/pipeline/test_animatediff_runtime.py -q`

### Journey Tests

None in Phase 1. GUI/user journeys belong to Phase 2 after runtime exists.

### Manual Testing

1. Verify capability detection against a WebUI without AnimateDiff installed.
2. Verify a dry-run mocked NJR with `animatediff` stage reaches runner dispatch.
3. Optional live validation only after unit/integration tests are green.

## Verification Criteria

### Success Criteria

1. `animatediff` can appear in `NormalizedJobRecord.stage_chain`.
2. Stage sequencer rejects invalid placement and accepts valid final-stage
   placement.
3. Missing AnimateDiff capability fails with a clear reason.
4. Runner dispatch produces a canonical MP4 artifact path in result metadata.
5. Focused pipeline tests pass.

### Failure Criteria

1. Any new direct execution path bypasses NJR or Queue/Runner semantics.
2. GUI files are touched in Phase 1.
3. AnimateDiff payload generation depends on hardcoded stale contract keys.
4. Tests require a live extension installation.

## Risk Assessment

### Low Risk Areas

`src/pipeline/video.py`: clip assembly path already works locally.  
`src/api/client.py`: `/sdapi/v1/scripts` access pattern already exists.

### Medium Risk Areas

`src/pipeline/run_plan.py`: currently lightweight and may need careful extension.
  
**Mitigation**: keep the change additive and stage-name driven.

`src/pipeline/prompt_pack_job_builder.py`: builder changes can ripple into tests.
  
**Mitigation**: keep stage emission gated by explicit `pipeline.animatediff_enabled`.

### High Risk Areas

AnimateDiff extension contract drift across versions.
  
**Mitigation**: capability-detect first, keep payload builder isolated in typed
helpers, and record an `extension_contract` string in runtime metadata.

### Rollback Plan

1. Revert `animatediff` stage registration and payload helpers.
2. Leave Movie Clips untouched.
3. Remove only AnimateDiff-specific tests and model helpers.

## Tech Debt Analysis

## Tech Debt Removed

1. Replaces stale repo assumptions with a current-state, contract-gated plan.

## Tech Debt Added

1. Introduces extension-specific capability logic in runtime code.

**Net Tech Debt**: +1, justified by explicit capability gating and typed helpers.

## Architecture Alignment

### Enforces Architecture v2.6

The PR keeps AnimateDiff inside the canonical runtime path:

PromptPack -> Builder -> NJR -> Queue -> Runner -> Outputs

No GUI shortcut and no controller-owned execution path is added.

### Follows Testing Standards

The spec requires deterministic pytest coverage with mocked WebUI responses.

### Maintains Separation of Concerns

1. API client handles capability discovery.
2. pipeline models handle typed config/results.
3. executor handles payload execution and artifact collection.
4. video helper handles MP4 assembly.

## Dependencies

### External

1. A1111-compatible WebUI with AnimateDiff extension installed for live use
2. FFmpeg for MP4 assembly

### Internal

1. `SDWebUIClient`
2. `VideoCreator`
3. NJR stage-chain builders
4. `PipelineRunner.run_njr`

## Timeline & Effort

### Breakdown

| Task | Effort | Duration |
|------|--------|----------|
| Typed models + capability helpers | 0.5 day | Day 1 |
| Sequencer / builder / RunPlan updates | 1 day | Day 1-2 |
| Executor + runner + video integration | 1.5 days | Day 2-3 |
| Tests and dry runs | 1 day | Day 3-4 |

**Total**: 4 working days

## Approval & Sign-Off

**Planner**: Codex  
**Executor**: Codex  
**Reviewer**: Rob

**Approval Status**: Pending human approval

## Next Steps

1. Approve this Phase 1 spec or request scope changes.
2. After approval, execute only the files listed in scope.
3. Defer GUI and learning to separate follow-on PR specs.
