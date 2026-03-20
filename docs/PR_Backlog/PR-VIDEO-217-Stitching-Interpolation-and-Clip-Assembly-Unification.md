# PR-VIDEO-217 - Stitching, Interpolation, and Clip-Assembly Unification

Status: Specification
Priority: HIGH
Effort: LARGE
Phase: Post-Unification Video Productization
Date: 2026-03-19

## Context & Motivation

### Problem Statement

StableNew has a Movie Clips surface and service, but post-video assembly is not
yet expressed as one canonical artifact path for generated video sequences.
Sequence outputs, stitched outputs, interpolated outputs, and clip exports need
to become StableNew-owned artifact/result paths instead of adjacent utilities.

### Why This Matters

This is the missing half of the older `PR-VIDEO-085` plan. Without it,
long-form video remains fragmented: sequence generation and final assembled
output do not share one clean provenance chain.

### Current Architecture

Current state:

- `MovieClipService` can assemble clips from images
- workflow-video and future sequence outputs are canonical artifacts
- there is no canonical assembled-video result layer that bridges sequence
  outputs into export-ready artifacts

### Reference

- `docs/ARCHITECTURE_v2.6.md`
- `docs/StableNew Roadmap v2.6.md`
- `docs/PR_Backlog/PR-VIDEO-216-Sequence-Orchestration-and-Segment-Planning.md`
- `docs/CompletedPR/PR-GUI-213-GUI-Queue-Only-and-Video-Surface-Cleanup.md`

## Goals & Non-Goals

### Goals

1. Add StableNew-owned contracts for stitched outputs and interpolated outputs.
2. Unify sequence assembly and Movie Clips under one canonical artifact/result
   path.
3. Make assembled-video provenance explicit: source segments, interpolation
   choices, export settings, and final output artifact.
4. Preserve Movie Clips as the user-facing assembly/export surface, but make it
   consume canonical post-video contracts instead of ad hoc bundles.

### Non-Goals

1. Do not build a rich timeline editor in this PR.
2. Do not redesign the full Movie Clips UI in this PR.
3. Do not add new backend runtimes for interpolation beyond a pluggable
   contract.
4. Do not add continuity or story planning in this PR.

## Guardrails

1. Post-video assembly remains StableNew-owned, not backend-owned.
2. Interpolation must be modeled as a pluggable service contract, not hardwired
   into the core artifact schema.
3. Movie Clips remains a consumer of canonical post-video contracts, not a
   second orchestration system.
4. Do not bypass canonical artifact/history/replay paths.

## Allowed Files

### Files to Create

| File | Purpose |
|------|---------|
| `src/video/assembly_models.py` | Typed models for stitched and interpolated outputs |
| `src/video/assembly_service.py` | StableNew-owned orchestration for post-video assembly |
| `src/video/interpolation_contracts.py` | Pluggable interpolation contract |
| `tests/video/test_assembly_models.py` | Model coverage |
| `tests/video/test_assembly_service.py` | Assembly orchestration coverage |
| `tests/video/test_interpolation_contracts.py` | Contract coverage |

### Files to Modify

| File | Reason |
|------|--------|
| `src/video/movie_clip_models.py` | Align clip result/manifest with canonical assembly provenance |
| `src/video/movie_clip_service.py` | Consume canonical assembly inputs and emit aligned artifacts |
| `src/video/video_export.py` | Reuse export logic through assembly contracts |
| `src/pipeline/pipeline_runner.py` | Preserve assembled-video artifact summaries when sequence assembly is used |
| `src/gui/views/movie_clips_tab_frame_v2.py` | Accept canonical sequence/assembly sources |
| `src/gui/view_contracts/movie_clips_contract.py` | UI contract alignment |
| `tests/video/test_movie_clip_service.py` | Updated service behavior |
| `tests/gui_v2/test_movie_clips_tab_v2.py` | UI handoff and source contract tests |
| `tests/pipeline/test_pipeline_runner.py` | assembled-video summary assertions |

### Forbidden Files

| File/Directory | Reason |
|----------------|--------|
| `src/controller/job_service.py` | No queue-policy changes |
| `src/controller/archive/` | No legacy surfaces |
| `src/gui/main_window_v2.py` | Avoid top-level GUI churn in this PR |

## Implementation Plan

### Step 1: Add assembly and interpolation contracts

Create StableNew-owned post-video models for:

- assembled sequence input
- stitched output
- interpolated output
- export-ready output bundle

Files:

- create `src/video/assembly_models.py`
- create `src/video/interpolation_contracts.py`
- create related tests

### Step 2: Build assembly orchestration service

Add a service that can:

- accept sequence or workflow-video outputs
- stitch ordered segments
- optionally invoke an interpolation provider
- emit one canonical assembled-video result bundle

Files:

- create `src/video/assembly_service.py`
- create `tests/video/test_assembly_service.py`

### Step 3: Align Movie Clips with canonical assembly contracts

Refactor Movie Clips data flow to consume canonical assembly inputs and emit
aligned manifests/results.

Files:

- modify `src/video/movie_clip_models.py`
- modify `src/video/movie_clip_service.py`
- modify `src/video/video_export.py`
- modify `tests/video/test_movie_clip_service.py`

### Step 4: Expose assembled artifacts to runner and UI

Add canonical assembled-video summaries to pipeline results where sequence
assembly occurs and ensure Movie Clips tab can consume those bundles.

Files:

- modify `src/pipeline/pipeline_runner.py`
- modify `src/gui/views/movie_clips_tab_frame_v2.py`
- modify `src/gui/view_contracts/movie_clips_contract.py`
- modify related tests

## Testing Plan

### Unit Tests

- `tests/video/test_assembly_models.py`
- `tests/video/test_interpolation_contracts.py`

### Integration Tests

- `tests/video/test_assembly_service.py`
- `tests/video/test_movie_clip_service.py`
- `tests/gui_v2/test_movie_clips_tab_v2.py`
- `tests/pipeline/test_pipeline_runner.py`

### Manual Testing

1. Produce a sequence output.
2. Run stitched assembly and verify a canonical artifact/manifests chain.
3. Run Movie Clips from the same source and verify the service consumes the
   same canonical source bundle.

## Verification Criteria

### Success Criteria

1. Sequence outputs can become stitched/interpolated artifacts without leaving
   canonical result paths.
2. Movie Clips consumes canonical sequence or assembly bundles instead of ad
   hoc source lists only.
3. Assembled-video outputs preserve provenance to source segments.

### Failure Criteria

1. Assembly results are side files with no canonical artifact summary.
2. Interpolation is hardwired into core contracts with no provider boundary.
3. Movie Clips still requires special-case sequence plumbing outside the
   canonical assembly contracts.

## Risk Assessment

### Low-Risk Areas

- new post-video contract files

### Medium-Risk Areas

- Movie Clips service alignment
  - Mitigation: keep existing clip-only path green while extending inputs

### High-Risk Areas

- provenance loss across stitched/interpolated outputs
  - Mitigation: make provenance fields mandatory in assembly result models

### Rollback Plan

Revert assembly-service integration and preserve Movie Clips current behavior
while keeping sequence generation intact.

## Tech Debt Analysis

### Tech Debt Removed

- disconnected sequence-to-export workflow
- clip/export logic detached from canonical video artifacts

### Tech Debt Intentionally Deferred

- continuity-aware clip assembly presets
  - Owner: `PR-VIDEO-218`
- story- and shot-aware export grouping
  - Owner: `PR-VIDEO-219`
- broad workspace UX polish
  - Owner: `PR-GUI-220`

## Documentation Updates

- `docs/StableNew Roadmap v2.6.md`
- `docs/PR_Backlog/StableNew_ComfyAware_Backlog_v2.6.md`

## Dependencies

### Internal

- sequence planning outputs from `PR-VIDEO-216`
- existing Movie Clips service and UI

### External

- FFmpeg remains the export dependency
- interpolation provider may initially be a no-op or mocked provider

## Approval & Execution

Planner: ChatGPT/Codex planning surface
Executor: Copilot or Codex
Reviewer: Rob
Approval Status: Pending

## Next Steps

1. Execute `PR-VIDEO-217` after `PR-VIDEO-216`.
2. Feed continuity metadata into assembly flows in `PR-VIDEO-218`.
3. Improve workflow ergonomics in `PR-GUI-220`.
