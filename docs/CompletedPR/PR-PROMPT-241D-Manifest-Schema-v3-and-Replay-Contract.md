# PR-PROMPT-241D - Manifest Schema v3 and Replay Contract

Status: Completed 2026-03-24
Priority: HIGH
Effort: MEDIUM
Phase: Prompt Optimizer v3 Replay Closure

## Summary

Promoted the prompt optimizer output from a stage-local analysis record into a
versioned `prompt_optimizer_v3` contract that now travels through stage
manifests, deterministic sidecars, and the pipeline replay/diagnostics
descriptors.

## Delivered

- added a versioned `prompt_optimizer_v3` decision bundle builder in the
  prompting registry
- emitted deterministic `prompt_optimizer_v3` sidecars next to stage manifests
- stamped `prompt_optimizer_v3` into prompt-enabled stage manifests for
  `txt2img`, `img2img`, `adetailer`, and `upscale`
- extended replay and diagnostics descriptors to include the replay-grade
  prompt optimizer bundle
- preserved the legacy `prompt_optimization` and `prompt_optimizer_analysis`
  records for compatibility

## Key Files

- `src/prompting/prompt_optimizer_registry.py`
- `src/pipeline/executor.py`
- `src/pipeline/result_contract_v26.py`
- `tests/pipeline/test_executor_prompt_optimizer.py`
- `tests/pipeline/test_result_contract_v26.py`

## Validation

- focused 241D slice:
  - `pytest tests/pipeline/test_executor_prompt_optimizer.py tests/pipeline/test_result_contract_v26.py tests/integration/test_prompt_optimizer_logging.py tests/integration/test_prompt_optimizer_payload_integration.py tests/unit/test_prompt_optimizer_orchestrator.py -q`
  - `14 passed in 0.72s`
- broader prompt regression:
  - `pytest tests/unit/test_stage_policy_engine.py tests/unit/test_prompt_intent_analyzer.py tests/unit/test_prompt_optimizer_orchestrator.py tests/unit/test_prompt_normalizer.py tests/unit/test_prompt_deduper.py tests/unit/test_sdxl_prompt_optimizer.py tests/unit/test_prompt_optimizer_service.py tests/integration/test_prompt_optimizer_logging.py tests/integration/test_prompt_optimizer_payload_integration.py tests/pipeline/test_executor_prompt_optimizer.py tests/pipeline/test_result_contract_v26.py -q`
  - `41 passed in 0.70s`