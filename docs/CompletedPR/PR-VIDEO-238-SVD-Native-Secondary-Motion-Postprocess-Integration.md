# PR-VIDEO-238 - SVD Native Secondary Motion Postprocess Integration

Status: Completed 2026-03-22

## Summary

This PR turned the previously observation-only secondary-motion contract into a
real SVD-native runtime path by injecting transient motion config from the
runner and executing the shared engine as SVD postprocess stage zero.

## Delivered

- added transient `postprocess.secondary_motion` config for SVD runtime handoff
- routed secondary motion through the SVD postprocess runner before face
  restore, interpolation, and upscale
- added worker-backed secondary-motion dispatch and manifest provenance stamping
- promoted compact secondary-motion summaries into SVD container metadata and
  stage results for replay closure

## Key Files

- `src/pipeline/pipeline_runner.py`
- `src/pipeline/executor.py`
- `src/video/svd_config.py`
- `src/video/svd_postprocess.py`
- `src/video/svd_postprocess_worker.py`
- `src/video/svd_runner.py`
- `src/video/svd_registry.py`
- `src/video/svd_native_backend.py`
- `tests/video/test_svd_postprocess.py`
- `tests/video/test_svd_postprocess_worker.py`
- `tests/pipeline/test_svd_runtime.py`

## Tests

Focused verification passed as part of the secondary-motion tranche:

- `pytest tests/video/test_svd_postprocess.py tests/video/test_svd_postprocess_worker.py tests/pipeline/test_svd_runtime.py tests/pipeline/test_pipeline_runner.py -q`
- result: included in the final focused tranche run with `58 passed`