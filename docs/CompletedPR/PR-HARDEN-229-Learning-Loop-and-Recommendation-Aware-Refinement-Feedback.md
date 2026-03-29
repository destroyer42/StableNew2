# PR-HARDEN-229 - Learning Loop and Recommendation-Aware Refinement Feedback

Status: Completed 2026-03-20

## Summary

This PR closed the adaptive-refinement tranche by connecting the existing
runtime provenance to the learning and recommendation layers without inventing
another schema. Learning records now carry a compact refinement summary, and
the recommendation engine can use that context conservatively while preserving
the existing evidence-tier safety rules.

## Delivered

- added `src/refinement/quality_metrics.py` for cheap local refinement-summary
  extraction and optional sharpness measurement
- updated `src/learning/learning_record_builder.py` so learning records can
  persist a compact `metadata["adaptive_refinement"]` block derived from the
  canonical runtime carrier
- updated `src/pipeline/pipeline_runner.py` so refinement learning context is
  passed into learning-record construction from the run result
- updated `src/learning/recommendation_engine.py` so refinement context can
  influence recommendation weighting conservatively without bypassing the
  existing evidence-tier rules

## Key Files

- `src/refinement/quality_metrics.py`
- `src/learning/learning_record_builder.py`
- `src/pipeline/pipeline_runner.py`
- `src/learning/recommendation_engine.py`
- `tests/refinement/test_quality_metrics.py`
- `tests/learning/test_learning_record_builder.py`
- `tests/learning/test_learning_hooks_pipeline_runner.py`
- `tests/learning_v2/test_recommendation_engine_refinement_context.py`

## Tests

Focused verification passed:

- `pytest tests/refinement/test_quality_metrics.py tests/learning/test_learning_record_builder.py tests/learning/test_learning_hooks_pipeline_runner.py tests/learning_v2/test_recommendation_engine_refinement_context.py tests/learning_v2/test_recommendation_engine_guards.py tests/learning_v2/test_recommendation_engine_evidence_tiering.py -q`
- result: `22 passed`
- `python -m compileall src/refinement src/learning src/pipeline tests/refinement tests/learning tests/learning_v2`
- `pytest --collect-only -q -rs` -> `2585 collected / 0 skipped`

## Documentation Updates

Bookkeeping closure recorded in:

- `docs/Subsystems/Learning/Learning_System_Spec_v2.6.md`
- `docs/REFINEMENT_POLICY_SCHEMA_v1.md`
- `docs/StableNew Roadmap v2.6.md`
- `docs/CompletedPlans/ADAPTIVE_REFINEMENT_EXECUTABLE_ROADMAP_v2.6.md`

## Deferred Debt

Intentionally deferred:

- GUI surfacing of adaptive-refinement recommendation context
  Future owner: later GUI follow-on
- any automatic policy retuning beyond current evidence-tier protections
  Future owner: later learning-specific planning work
