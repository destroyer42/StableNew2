# PR-HARDEN-225 - Prompt Intent Analysis and Observation-Only Decision Capture

Status: Completed 2026-03-20

## Summary

This PR added the first real adaptive-refinement runtime behavior while keeping
the tranche dark-launched and observation-only. The runner can now infer prompt
intent and emit a canonical decision bundle under one `adaptive_refinement`
metadata block without mutating any stage config or executor payload.

## Delivered

- added `src/refinement/prompt_intent_analyzer.py` on top of the existing
  prompt infrastructure
- added `src/refinement/subject_scale_policy_service.py` with observation-only
  bundle assembly and null-detector support
- added the detector package boundary in `src/refinement/detectors/`
- updated `src/refinement/refinement_policy_registry.py` so the default path
  emits `observe_only_v1` and empty overrides
- updated `src/pipeline/pipeline_runner.py` to stamp
  `run_result.metadata["adaptive_refinement"]` only when the feature is enabled
  in `observe` mode
- froze the observation bundle shape in `docs/REFINEMENT_POLICY_SCHEMA_v1.md`

## Key Files

- `src/refinement/prompt_intent_analyzer.py`
- `src/refinement/subject_scale_policy_service.py`
- `src/refinement/detectors/base_detector.py`
- `src/refinement/detectors/null_detector.py`
- `src/refinement/refinement_policy_registry.py`
- `src/pipeline/pipeline_runner.py`
- `docs/REFINEMENT_POLICY_SCHEMA_v1.md`

## Tests

Focused verification passed:

- `pytest tests/refinement/test_prompt_intent_analyzer.py tests/refinement/test_subject_scale_policy_service.py tests/pipeline/test_pipeline_runner.py -q`
- result: `18 passed`
- `python -m compileall src/refinement src/pipeline/pipeline_runner.py tests/refinement tests/pipeline/test_pipeline_runner.py`

## Documentation Updates

Bookkeeping closure recorded in:

- `docs/REFINEMENT_POLICY_SCHEMA_v1.md`
- `docs/StableNew Roadmap v2.6.md`
- `docs/CompletedPlans/ADAPTIVE_REFINEMENT_EXECUTABLE_ROADMAP_v2.6.md`

## Deferred Debt

Intentionally deferred:

- real detector-backed subject assessment
  Future owner: `PR-HARDEN-226`
- manifest, embedded-image-metadata, and diagnostics reuse of the same
  refinement carrier
  Future owners: `PR-HARDEN-227` and `PR-HARDEN-228`
- any behavior-changing actuation
  Future owners: `PR-HARDEN-227` and `PR-HARDEN-228`
