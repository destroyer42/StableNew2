# PR-VIDEO-207 - NJR Video Contract Completion

Status: Completed 2026-03-18

## Summary

This PR closes the remaining gap between the documented v2.6 architecture and
the live video runtime.

Image and video were already both NJR-driven at execution time, but some
history and manifest consumers still depended on stage-specific summary keys
like `svd_native_artifact` and `animatediff_artifact`.

This PR adds a backend-agnostic video summary layer while keeping the stage-
specific keys for compatibility.

## Runtime Changes

### 1. PipelineRunner now emits generic video artifact summaries

[pipeline_runner.py](/c:/Users/rob/projects/StableNew/src/pipeline/pipeline_runner.py)
now writes generic video metadata for video stages:

- `metadata["video_artifacts"][stage_name]`
- `metadata["video_primary_artifact"]`
- `metadata["video_primary_backend_id"]`
- `metadata["video_primary_stage"]`

These summaries carry:

- stage name
- backend id
- canonical output paths
- manifest paths
- thumbnail path
- count
- canonical artifact records

The existing compatibility keys remain:

- `animatediff_artifact`
- `svd_native_artifact`

### 2. Generic video summary is used for NJR thumbnail hydration

[pipeline_runner.py](/c:/Users/rob/projects/StableNew/src/pipeline/pipeline_runner.py)
now prefers `video_primary_artifact.thumbnail_path` when writing final output
state back onto the NJR.

That keeps the runner aligned with the new backend-agnostic metadata contract.

### 3. AppController SVD history reconstruction now prefers generic metadata

[app_controller.py](/c:/Users/rob/projects/StableNew/src/controller/app_controller.py)
now extracts video artifact summaries through a generic helper that prefers:

- `video_artifacts`
- `video_primary_artifact`
- `video_backend_results`

before falling back to legacy stage-specific summary keys.

This keeps the current SVD-facing UI working while aligning the extraction path
with the backend-agnostic contract needed for future video backends.

### 4. Job history panel is no longer hard-coded to stage-specific video keys

[job_history_panel_v2.py](/c:/Users/rob/projects/StableNew/src/gui/job_history_panel_v2.py)
now iterates generic video artifact aggregates first, then falls back to legacy
stage-specific keys.

That means the panel can now derive:

- primary artifact
- image/video count
- output folder
- SVD-button enablement

from the generic video summary contract rather than only from `animatediff` and
`svd_native` compatibility keys.

## Verification

Passed:

- `pytest tests/pipeline/test_pipeline_runner.py tests/controller/test_app_controller_svd.py tests/gui_v2/test_job_history_panel_v2.py tests/gui_v2/test_job_history_panel_display.py tests/video/test_video_backend_registry.py tests/pipeline/test_animatediff_runtime.py tests/pipeline/test_svd_runtime.py -q`
- `python -m compileall src/pipeline/pipeline_runner.py src/controller/app_controller.py src/gui/job_history_panel_v2.py tests/pipeline/test_pipeline_runner.py tests/controller/test_app_controller_svd.py tests/gui_v2/test_job_history_panel_v2.py`

## Documentation Updates

Updated:

- [README.md](/c:/Users/rob/projects/StableNew/README.md)
- [StableNew Roadmap v2.6.md](/c:/Users/rob/projects/StableNew/docs/StableNew%20Roadmap%20v2.6.md)
- [MIGRATION_CLOSURE_EXECUTABLE_BACKLOG_v2.6-1.md](/c:/Users/rob/projects/StableNew/docs/CompletedPlans/MIGRATION_CLOSURE_EXECUTABLE_BACKLOG_v2.6-1.md)
- [StableNew_ComfyAware_Backlog_v2.6.md](/c:/Users/rob/projects/StableNew/docs/CompletedPlans/StableNew_ComfyAware_Backlog_v2.6.md)

## Outstanding Debt

Intentionally deferred:

- a dedicated generic video history surface still does not exist
  Future owner: `PR-GUI-213`
- backend-specific workflow compilation and replay metadata remain part of the
  Comfy tranche
  Future owners: `PR-COMFY-208`, `PR-COMFY-209`, `PR-COMFY-210`

## Next PR

Next planned PR: `PR-COMFY-208`
