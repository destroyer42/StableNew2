# PR-VIDEO-240 - Workflow Video Secondary Motion Parity and Replay Closure

Status: Completed 2026-03-22

## Summary

This PR closed backend parity by adding a StableNew-owned workflow-video
extract/apply/re-encode path that promotes the re-encoded artifact while
preserving provenance about the original workflow output.

## Delivered

- added `secondary_motion_video_reencode.py` for workflow-video frame extract,
  shared-engine application, and FFmpeg re-encode
- promoted the re-encoded video to the canonical primary artifact when motion
  is applied
- retained original workflow-video source artifact lineage in raw result and
  manifest payloads
- carried the same compact secondary-motion summary shape used by SVD and
  AnimateDiff into workflow-video replay and container metadata

## Key Files

- `src/video/comfy_workflow_backend.py`
- `src/video/motion/secondary_motion_video_reencode.py`
- `tests/video/test_comfy_workflow_backend.py`

## Tests

Focused verification passed as part of the final tranche run:

- `pytest tests/video/test_comfy_workflow_backend.py tests/pipeline/test_pipeline_runner.py -q`
- result: included in the final focused tranche run with `58 passed`