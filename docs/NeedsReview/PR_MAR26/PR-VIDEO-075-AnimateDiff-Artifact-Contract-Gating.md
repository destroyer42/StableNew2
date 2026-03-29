# PR-VIDEO-075: AnimateDiff Artifact Contract Gating

## Goal

Complete AnimateDiff Phase 1 as a contract-gated follow-on path, not a parallel runtime branch.

## Scope

- Preserve canonical artifact metadata for AnimateDiff stage results.
- Surface manifest paths and canonical artifact records through `PipelineRunner.run_njr()`.
- Lock the contract with focused runtime and runner tests.

## Changes

### Runtime

- `run_animatediff_stage()` now records:
  - `output_path`
  - `output_paths`
  - `source_image_path`
  - `frame_path_count`
  - `manifest_path`
  - `manifest_paths`
  - `count`
- The returned metadata already carried a canonical `artifact` block; this PR ensures the rest of the stage result is aligned with it.

### Runner

- `animatediff_artifact` in pipeline-run metadata now includes:
  - `video_paths`
  - `output_paths`
  - `manifest_paths`
  - `primary_path`
  - `count`
  - `artifacts`

## Why

Before this PR, AnimateDiff could write a manifest file to disk without carrying that manifest path or canonical artifact record back into the run result summary. That made downstream history/replay consumers weaker than the equivalent SVD path and left AnimateDiff as an under-specified video branch.

## Tests

- `tests/pipeline/test_animatediff_runtime.py`
- `tests/pipeline/test_pipeline_runner.py`

## Result

AnimateDiff remains a follow-on video stage, but it now participates in the same artifact-first contract used by the rest of the canonical runtime.
