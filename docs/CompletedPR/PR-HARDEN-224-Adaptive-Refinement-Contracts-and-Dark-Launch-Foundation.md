# PR-HARDEN-224 - Adaptive Refinement Contracts and Dark-Launch Foundation

Status: Completed 2026-03-20

## Summary

This PR established the canonical adaptive-refinement contract without changing
runtime behavior. The goal was to create one stable, NJR-backed intent surface
and a dedicated `src/refinement/` package boundary before any runner or stage
mutation work began.

## Delivered

- added `src/refinement/__init__.py` as the package boundary
- added `src/refinement/refinement_policy_models.py` with
  `AdaptiveRefinementIntent` and `RefinementDecisionBundle`
- added `src/refinement/refinement_policy_registry.py` with the default no-op
  registry
- extended `src/pipeline/config_contract_v26.py` with the canonical
  `adaptive_refinement` intent key and extraction helpers
- updated `src/pipeline/job_builder_v2.py`,
  `src/pipeline/prompt_pack_job_builder.py`, and
  `src/pipeline/cli_njr_builder.py` so the nested intent survives builder paths
- added the minimal typed carrier in `src/pipeline/job_requests_v2.py` required
  to preserve the nested contract through request-building flows
- added import-boundary coverage in
  `tests/refinement/test_refinement_layer_imports.py`
- added the active schema document `docs/Architecture/REFINEMENT_POLICY_SCHEMA_v1.md`

## Key Files

- `src/refinement/refinement_policy_models.py`
- `src/refinement/refinement_policy_registry.py`
- `src/pipeline/config_contract_v26.py`
- `src/pipeline/job_builder_v2.py`
- `src/pipeline/prompt_pack_job_builder.py`
- `src/pipeline/cli_njr_builder.py`
- `docs/Architecture/REFINEMENT_POLICY_SCHEMA_v1.md`

## Tests

Focused verification passed:

- `pytest tests/refinement/test_refinement_policy_models.py tests/refinement/test_refinement_layer_imports.py tests/pipeline/test_config_contract_v26.py tests/pipeline/test_job_builder_v2.py tests/pipeline/test_prompt_pack_job_builder.py tests/pipeline/test_cli_njr_builder.py -q`
- result: `23 passed`
- `python -m compileall src/refinement src/pipeline/config_contract_v26.py src/pipeline/job_builder_v2.py src/pipeline/prompt_pack_job_builder.py src/pipeline/cli_njr_builder.py tests/refinement tests/pipeline/test_config_contract_v26.py tests/pipeline/test_job_builder_v2.py tests/pipeline/test_prompt_pack_job_builder.py tests/pipeline/test_cli_njr_builder.py`

## Documentation Updates

Bookkeeping closure recorded in:

- `docs/DOCS_INDEX_v2.6.md`
- `docs/Architecture/REFINEMENT_POLICY_SCHEMA_v1.md`
- `docs/StableNew Roadmap v2.6.md`
- `docs/CompletedPlans/ADAPTIVE_REFINEMENT_EXECUTABLE_ROADMAP_v2.6.md`

## Deferred Debt

Intentionally deferred:

- observation-only analyzer and decision capture
  Future owner: `PR-HARDEN-225`
- real detector boundary and optional OpenCV assessment
  Future owner: `PR-HARDEN-226`
- any actuation against ADetailer, prompt text, or upscale stages
  Future owners: `PR-HARDEN-227` and `PR-HARDEN-228`
