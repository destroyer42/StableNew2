# PR-VIDEO-239 - AnimateDiff Secondary Motion Frame Pipeline Integration

Status: Completed 2026-03-22

## Summary

This PR inserted the shared secondary-motion engine into the existing
AnimateDiff frame pipeline, keeping output semantics stable while making the
apply path canonical and replay-safe.

## Delivered

- injected transient secondary-motion runtime config for AnimateDiff stages
- applied shared motion after frame write and before MP4 assembly
- recorded canonical secondary-motion provenance in stage metadata, manifests,
  replay payloads, and container metadata
- added regression coverage for apply-mode handoff and provenance writeback

## Key Files

- `src/pipeline/pipeline_runner.py`
- `src/pipeline/executor.py`
- `src/video/animatediff_backend.py`
- `tests/pipeline/test_animatediff_runtime.py`
- `tests/pipeline/test_pipeline_runner.py`

## Tests

Focused verification passed as part of the final tranche run:

- `pytest tests/pipeline/test_animatediff_runtime.py tests/pipeline/test_pipeline_runner.py -q`
- result: included in the final focused tranche run with `58 passed`