# PR-HARDEN-227 - Safe ADetailer Adaptive Policy Application

Status: Completed 2026-03-20

## Summary

This PR delivered the first behavior-changing adaptive-refinement slice while
keeping the rollout tightly scoped to ADetailer only. StableNew can now assess
each image, choose a conservative ADetailer policy, apply only stage-local
overrides, and persist the exact same refinement carrier into manifests and
embedded image metadata.

## Delivered

- updated `src/refinement/refinement_policy_registry.py` with the first
  ADetailer-safe v1 policy presets
- updated `src/pipeline/pipeline_runner.py` so `mode="adetailer"` and
  `mode="full"` can build per-image decisions and copy only ADetailer-local
  overrides into per-image stage config
- ensured the runner does not mutate prompts or non-ADetailer stage configs
- updated `src/pipeline/executor.py` so ADetailer payload construction honors
  the refinement-provided override keys and persists the canonical
  `adaptive_refinement` block into stage metadata/manifests
- added manifest-facing coverage in
  `tests/pipeline/test_executor_refinement_manifest.py`

## Key Files

- `src/refinement/refinement_policy_registry.py`
- `src/pipeline/pipeline_runner.py`
- `src/pipeline/executor.py`
- `tests/pipeline/test_pipeline_runner.py`
- `tests/pipeline/test_executor_adetailer.py`
- `tests/pipeline/test_executor_refinement_manifest.py`

## Tests

Focused verification passed:

- `pytest tests/pipeline/test_pipeline_runner.py tests/pipeline/test_executor_adetailer.py tests/pipeline/test_executor_refinement_manifest.py -q`
- result: `24 passed`
- `python -m compileall src/refinement/refinement_policy_registry.py src/pipeline/pipeline_runner.py src/pipeline/executor.py tests/pipeline/test_pipeline_runner.py tests/pipeline/test_executor_adetailer.py tests/pipeline/test_executor_refinement_manifest.py`
- `pytest --collect-only -q -rs` -> `2568 collected / 0 skipped`

## Documentation Updates

Bookkeeping closure recorded in:

- `docs/REFINEMENT_POLICY_SCHEMA_v1.md`
- `docs/Image_Metadata_Contract_v2.6.md`
- `docs/StableNew Roadmap v2.6.md`
- `docs/PR_Backlog/ADAPTIVE_REFINEMENT_EXECUTABLE_ROADMAP_v2.6.md`

## Deferred Debt

Intentionally deferred:

- prompt patching and upscale policy application
  Future owner: `PR-HARDEN-228`
- learning-loop and recommendation-aware evaluation of refinement behavior
  Future owner: `PR-HARDEN-229`
