# PR-VIDEO-240 - Workflow Video Secondary Motion Parity and Replay Closure

Status: Completed 2026-03-24

## Summary

This PR closed workflow-video parity by hardening the existing StableNew-owned
extract/apply/re-encode path so it is skip-safe, preserves the original
workflow output as canonical fallback, and carries the same compact
secondary-motion summary surfaces as SVD and AnimateDiff.

## Delivered

- made workflow-video secondary-motion application skip-safe for missing FFmpeg,
  extraction failures, worker failures, and re-encode failures
- preserved the original workflow output as the canonical primary artifact when
  secondary motion is unavailable
- promoted the re-encoded video only when secondary motion applies
- retained original workflow-video source artifact lineage in raw result,
  manifest payloads, replay fragments, and container metadata
- carried the same compact secondary-motion summary shape used by SVD and
  AnimateDiff into workflow-video result, manifest, replay, and container
  surfaces

## Key Files

- `src/video/comfy_workflow_backend.py`
- `src/video/motion/secondary_motion_video_reencode.py`
- `tests/video/test_secondary_motion_video_reencode.py`
- `tests/video/test_comfy_workflow_backend.py`
- `tests/video/test_video_backend_registry.py`

## Tests

Focused verification passed as part of the final tranche run:

- `pytest tests/video/test_secondary_motion_video_reencode.py tests/video/test_comfy_workflow_backend.py tests/video/test_video_backend_registry.py -q`
- result: `13 passed in 1.89s`
