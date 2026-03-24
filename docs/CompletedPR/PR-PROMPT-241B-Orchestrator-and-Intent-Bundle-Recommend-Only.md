# PR-PROMPT-241B - Orchestrator and Intent Bundle Recommend-Only

Status: Completed 2026-03-24

## Summary

This PR added a StableNew-owned prompt optimizer orchestrator and typed
recommend-only analysis bundle so executor stages now record prompt context,
intent signals, and structured recommendations without introducing any new
prompt or config mutation beyond the existing format-only optimizer behavior.

## Delivered

- added typed prompt contracts for source context, prompt context, intent
  bundles, recommendations, and analysis bundles
- added a rule-based prompt intent analyzer that infers shot/style/pose,
  sensitivity signals, and prompt conflicts from the existing formatter input
- added a recommend-only prompt optimizer orchestrator that wraps the existing
  formatter service while preserving current prompt outputs
- updated executor prompt-optimizer integration so `adetailer`, `txt2img`, and
  `img2img` record `prompt_optimizer_analysis` alongside the existing
  `prompt_optimization` manifest block
- stabilized the prompt-optimizer pipeline tests so they no longer depend on
  live runtime admission state

## Key Files

- `src/prompting/contracts.py`
- `src/prompting/prompt_intent_analyzer.py`
- `src/prompting/prompt_optimizer_orchestrator.py`
- `src/prompting/prompt_optimizer_registry.py`
- `src/pipeline/executor.py`
- `tests/unit/test_prompt_intent_analyzer.py`
- `tests/unit/test_prompt_optimizer_orchestrator.py`
- `tests/integration/test_prompt_optimizer_logging.py`
- `tests/pipeline/test_executor_prompt_optimizer.py`

## Tests

Focused verification passed as part of the final tranche run:

- `pytest tests/unit/test_prompt_intent_analyzer.py tests/unit/test_prompt_optimizer_orchestrator.py tests/unit/test_prompt_normalizer.py tests/unit/test_prompt_deduper.py tests/unit/test_sdxl_prompt_optimizer.py tests/unit/test_prompt_optimizer_service.py tests/integration/test_prompt_optimizer_logging.py tests/integration/test_prompt_optimizer_payload_integration.py tests/pipeline/test_executor_prompt_optimizer.py -q`
- result: `32 passed in 0.58s`
