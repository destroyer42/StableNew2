# PR-HARDEN-226 - Detector Boundary and Optional OpenCV Subject Assessment

Status: Specification
Priority: HIGH
Effort: MEDIUM
Phase: Adaptive Refinement Assessment Layer
Date: 2026-03-20

## Context & Motivation

### Current Repo Truth

After `PR-HARDEN-225`, StableNew can emit observation bundles, but the default
assessment path is still detector-free. That keeps the metadata contract moving,
but it does not deliver real subject-scale assessment yet.

### Specific Problem

The research memo placed optional detector support after runner wiring and very
close to stage mutation. That would make the first behavior-changing PR either
inert or under-tested.

### Why This PR Exists Now

StableNew needs a real assessment boundary before it starts mutating stage
behavior. This PR delivers that boundary while keeping actuation turned off.

### Reference

- `docs/REFINEMENT_POLICY_SCHEMA_v1.md`
- `docs/PR_Backlog/ADAPTIVE_REFINEMENT_EXECUTABLE_ROADMAP_v2.6.md`
- `docs/PR_Backlog/PR-HARDEN-225-Prompt-Intent-Analysis-and-Observation-Only-Decision-Capture.md`

## Goals & Non-Goals

### Goals

1. Implement the real detector boundary under `src/refinement/detectors/`.
2. Add an optional OpenCV-backed face detector without introducing a mandatory
   dependency.
3. Version and centralize subject-scale threshold logic.
4. Enrich observation bundles with real assessment data when OpenCV is
   available.

### Non-Goals

1. Do not change stage behavior in this PR.
2. Do not add prompt patches in this PR.
3. Do not add manifest or executor payload changes in this PR.
4. Do not change learning records in this PR.

## Guardrails

1. The OpenCV path must be optional and degrade to `NullDetector`.
2. Use only OpenCV resources already present in the repo dependency surface.
3. Do not download detector models or require network access.
4. Thresholds and detector parameters must be explicit and versioned, not magic
   constants buried in runner code.
5. Assessment must happen at most once per source image per run path, with
   runner-owned caching and deterministic reuse by downstream stages.
6. Detector execution must be bounded by explicit timeout/fallback behavior and
   may never fail the overall job merely because adaptive assessment degraded.

## Allowed Files

### Files to Create

| File | Purpose |
| ------ | ------- |
| `src/refinement/detectors/opencv_face_detector.py` | Optional OpenCV detector implementation |
| `tests/refinement/test_opencv_face_detector.py` | Optional detector coverage with `pytest.importorskip("cv2")` |
| `tests/fixtures/refinement/subject_scale_small.png` | Deterministic fixture image |
| `tests/fixtures/refinement/subject_scale_profile.png` | Deterministic fixture image |

### Files to Modify

| File | Reason |
| ------ | ------ |
| `src/refinement/subject_scale_policy_service.py` | Centralize threshold config and algorithm versioning |
| `src/refinement/detectors/__init__.py` | Export detector implementations |
| `src/pipeline/pipeline_runner.py` | Resolve detector preference and enrich observation bundles |
| `tests/refinement/test_subject_scale_policy_service.py` | Real-assessment threshold assertions |
| `tests/pipeline/test_pipeline_runner.py` | Detector-preference and fallback assertions |
| `docs/REFINEMENT_POLICY_SCHEMA_v1.md` | Document detector id and assessment fields |

### Forbidden Files

| File/Directory | Reason |
| ---------------- | ------ |
| `pyproject.toml` | OpenCV is already present; do not churn dependencies |
| `requirements-svd.txt` | OpenCV is already present; do not churn dependencies |
| `src/pipeline/executor.py` | No actuation or manifest work yet |
| `src/learning/**` | No learning work yet |

## Implementation Plan

### Step 1: Implement the optional OpenCV detector

Required details:

- use OpenCV's built-in cascade resources under `cv2.data.haarcascades`
- use `haarcascade_frontalface_default.xml` and `haarcascade_profileface.xml`
- perform profile detection on both the original and horizontally flipped image
  so left/right profiles are covered
- merge overlapping detections with an IoU-based dedupe pass in StableNew code
- raise a clear runtime error only when the OpenCV detector is explicitly
  requested and unavailable; otherwise the system must fall back to null

Files:

- create `src/refinement/detectors/opencv_face_detector.py`
- create `tests/refinement/test_opencv_face_detector.py`

### Step 2: Freeze assessment thresholds and algorithm versioning

Required details:

- keep threshold defaults explicit in `SubjectScalePolicyConfig`
- use the initial bands from the research memo:
  `micro < 0.004`, `small < 0.012`, `medium < 0.030`, else `large`
- stamp `algorithm_version` into the assessment bundle

Files:

- modify `src/refinement/subject_scale_policy_service.py`
- modify `tests/refinement/test_subject_scale_policy_service.py`

### Step 3: Wire detector preference resolution into the runner

Required details:

- read `detector_preference` from the nested refinement intent
- default to `null`
- support `opencv` as the first real detector id
- when OpenCV is unavailable and `detector_preference="opencv"`, record a note
  explaining fallback instead of failing the job
- cache the assessment result once per image and reuse it for downstream stage
  decisions
- add a bounded timeout/fallback rule so detector slowdown degrades to a note
  plus `NullDetector` behavior rather than stalling the pipeline

Files:

- modify `src/pipeline/pipeline_runner.py`
- modify `tests/pipeline/test_pipeline_runner.py`

### Step 4: Extend the schema doc

Required details:

- document detector ids, assessment fields, threshold bands, and fallback notes
- keep actuation fields explicitly absent from this PR

Files:

- modify `docs/REFINEMENT_POLICY_SCHEMA_v1.md`

## Testing Plan

### Unit Tests

- `tests/refinement/test_subject_scale_policy_service.py`
- `tests/refinement/test_opencv_face_detector.py`

### Integration Tests

- `tests/pipeline/test_pipeline_runner.py`

### Journey or Smoke Coverage

- one observation-mode smoke path with `detector_preference="opencv"`

### Manual Verification

1. Run observation mode with `detector_preference="null"` and confirm the
   bundle still completes.
2. Run observation mode with `detector_preference="opencv"` in an environment
   that has OpenCV and confirm real assessment fields appear.
3. Confirm missing-OpenCV environments fall back cleanly without job failure.

Suggested command set:

- `pytest tests/refinement/test_subject_scale_policy_service.py tests/refinement/test_opencv_face_detector.py tests/pipeline/test_pipeline_runner.py -q`

## Verification Criteria

### Success Criteria

1. StableNew has a real subject-assessment path that remains optional.
2. Assessment thresholds are centralized and versioned.
3. Observation bundles become richer when OpenCV is available, while fallback
   behavior remains deterministic.
4. Detector work is cached per image and does not repeat independently per
   downstream stage.

### Failure Criteria

1. OpenCV becomes a mandatory dependency.
2. The PR downloads models or requires network access.
3. Thresholds or detector settings are hidden in runner code.
4. Detector work repeats per stage or can stall the job without deterministic
   fallback.

## Risk Assessment

### Low-Risk Areas

- null-fallback path

### Medium-Risk Areas With Mitigation

- OpenCV cascade false positives or duplicate boxes
  - Mitigation: deterministic fixture tests and IoU-based dedupe logic

### High-Risk Areas With Mitigation

- environment-sensitive behavior when OpenCV is unavailable
  - Mitigation: explicit fallback notes and `pytest.importorskip("cv2")` for
    optional tests

### Rollback Plan

Remove the OpenCV detector path and retain the null-detector observation flow.

## Critical Appraisal and Incorporated Corrections

1. Weakness: the original plan placed real detector support too late.
   Incorporated correction: detector rollout lands before any actuation PR.
2. Weakness: the original plan left threshold choices as inline examples.
   Incorporated correction: this PR requires centralized threshold config and
   version stamping.
3. Weakness: the original plan risked dependency churn.
   Incorporated correction: this PR forbids package-file edits because OpenCV is
   already present in the optional dependency surface.
4. Weakness: the original plan left detector cost and failure behavior too
   implicit.
   Incorporated correction: this PR requires per-image caching plus explicit
   timeout/fallback degradation.

## Tech Debt Analysis

### Debt Removed

- missing real subject-assessment path
- missing detector abstraction with safe fallback

### Debt Intentionally Deferred

- ADetailer actuation
  - Owner: `PR-HARDEN-227`
- prompt patch and upscale policy actuation
  - Owner: `PR-HARDEN-228`

## Documentation Updates

- update `docs/REFINEMENT_POLICY_SCHEMA_v1.md`
- update `docs/Image_Metadata_Contract_v2.6.md` only if assessment fields are
  mirrored there

## Dependencies

### Internal Module Dependencies

- `src/refinement/subject_scale_policy_service.py`
- `src/pipeline/pipeline_runner.py`

### External Tools or Runtimes

- OpenCV is optional and already available through the existing optional
  dependency surface

## Approval & Execution

Planner: GitHub Copilot / ChatGPT planning surface
Executor: Copilot or Codex
Reviewer: Rob
Approval Status: Pending

## Next Steps

1. Execute `PR-HARDEN-226`.
2. After assessment stability is confirmed, execute `PR-HARDEN-227` for the
   first actuation rollout.
