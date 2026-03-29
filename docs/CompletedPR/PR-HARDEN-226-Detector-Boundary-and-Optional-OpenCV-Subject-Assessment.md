# PR-HARDEN-226 - Detector Boundary and Optional OpenCV Subject Assessment

Status: Completed 2026-03-20

## Summary

This PR added the first real detector-backed subject-assessment path while
keeping adaptive refinement observation-only. StableNew now has an optional
OpenCV detector, centralized and versioned threshold logic, runner-owned
caching, and deterministic timeout/fallback behavior.

## Delivered

- added `src/refinement/detectors/opencv_face_detector.py` using OpenCV cascade
  resources already present in the environment
- updated `src/refinement/detectors/__init__.py` to export the OpenCV detector
- extended `src/refinement/subject_scale_policy_service.py` with explicit
  threshold bands, algorithm version stamping, and richer assessment fields
- updated `src/pipeline/pipeline_runner.py` to:
  - resolve detector preference from the nested refinement intent
  - degrade cleanly to `NullDetector` when OpenCV is unavailable
  - cache assessments per output path
  - enforce timeout/error fallback notes instead of failing the job
  - enrich `adaptive_refinement.decision_bundle.observation` with
    `subject_assessment` and `image_assessments`
- updated `docs/Architecture/REFINEMENT_POLICY_SCHEMA_v1.md` with detector ids, assessment
  fields, threshold bands, and fallback note semantics

## Key Files

- `src/refinement/detectors/opencv_face_detector.py`
- `src/refinement/detectors/__init__.py`
- `src/refinement/subject_scale_policy_service.py`
- `src/pipeline/pipeline_runner.py`
- `docs/Architecture/REFINEMENT_POLICY_SCHEMA_v1.md`

## Tests

Focused verification passed:

- `pytest tests/refinement/test_subject_scale_policy_service.py tests/refinement/test_opencv_face_detector.py tests/pipeline/test_pipeline_runner.py -q`
- result: `26 passed`
- `python -m compileall src/refinement src/pipeline/pipeline_runner.py tests/refinement tests/pipeline/test_pipeline_runner.py`
- `pytest --collect-only -q -rs` -> `2565 collected / 0 skipped`

## Documentation Updates

Bookkeeping closure recorded in:

- `docs/Architecture/REFINEMENT_POLICY_SCHEMA_v1.md`
- `docs/StableNew Roadmap v2.6.md`
- `docs/CompletedPlans/ADAPTIVE_REFINEMENT_EXECUTABLE_ROADMAP_v2.6.md`

## Deferred Debt

Intentionally deferred:

- ADetailer-safe adaptive actuation
  Future owner: `PR-HARDEN-227`
- prompt patch and upscale policy application
  Future owner: `PR-HARDEN-228`
- manifest, embedded-image-metadata, diagnostics, and learning reuse of the
  canonical refinement carrier
  Future owners: `PR-HARDEN-227`, `PR-HARDEN-228`, and `PR-HARDEN-229`
