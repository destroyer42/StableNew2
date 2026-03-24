# PR-PROMPT-241C - Stage Policy Engine and Auto-Safe Fill Missing

Status: Completed 2026-03-24

## Summary

This PR extended the prompt optimizer foundation into a typed, recommendable,
and auto-safe stage policy layer that can fill only missing or explicit `AUTO`
settings while preserving every explicit user choice.

## Delivered

- added typed stage policy contracts and a StableNew-owned stage policy engine
- generated prompt-aware stage policy decisions from `PromptContext` and
  `PromptIntentBundle`
- applied safe fills for `txt2img`, `img2img`, `ADetailer`, and `upscale`
  without overriding explicit user settings
- recorded stage policy decisions under `prompt_optimizer_analysis.stage_policy`
  in executor manifests
- aligned the standalone payload-builder path with the same prompt policy logic

## Key Files

- `src/prompting/contracts.py`
- `src/prompting/stage_policy_engine.py`
- `src/prompting/__init__.py`
- `src/pipeline/executor.py`
- `src/pipeline/payload_builder.py`
- `tests/unit/test_stage_policy_engine.py`
- `tests/pipeline/test_executor_prompt_optimizer.py`
- `tests/integration/test_prompt_optimizer_payload_integration.py`

## Tests

Focused verification passed:

- `pytest tests/unit/test_stage_policy_engine.py tests/unit/test_prompt_intent_analyzer.py tests/unit/test_prompt_optimizer_orchestrator.py tests/unit/test_prompt_normalizer.py tests/unit/test_prompt_deduper.py tests/unit/test_sdxl_prompt_optimizer.py tests/unit/test_prompt_optimizer_service.py tests/integration/test_prompt_optimizer_logging.py tests/integration/test_prompt_optimizer_payload_integration.py tests/pipeline/test_executor_prompt_optimizer.py -q`
- result: `38 passed in 0.70s`