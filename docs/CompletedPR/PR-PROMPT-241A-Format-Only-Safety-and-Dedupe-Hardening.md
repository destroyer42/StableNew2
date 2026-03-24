# PR-PROMPT-241A - Format-Only Safety and Dedupe Hardening

Status: Completed 2026-03-24

## Summary

This PR hardened the existing prompt optimizer so its default path stays
format-only and fail-open while no longer collapsing distinct LoRA variants,
weighted syntax, or the configured ordering-preservation flags into no-op
behavior.

## Delivered

- changed dedupe identity so LoRA tokens retain full normalized token identity,
  including distinct weight variants
- stopped weighted prompt syntax from collapsing into unweighted semantic keys
  during duplicate detection
- made `preserve_unknown_order` real by keeping unknown chunks in original
  order instead of forcing them to the tail by bucket order
- made `preserve_lora_relative_order` real by preserving LoRA placement when
  the flag is enabled while still supporting the old “move to end” behavior
  when disabled
- kept optimizer outputs fail-open and preserved the public string bucket shape
  in `PromptOptimizationResult`

## Key Files

- `src/prompting/prompt_normalizer.py`
- `src/prompting/prompt_types.py`
- `src/prompting/sdxl_prompt_optimizer.py`
- `tests/unit/test_prompt_normalizer.py`
- `tests/unit/test_prompt_deduper.py`
- `tests/unit/test_sdxl_prompt_optimizer.py`

## Tests

Focused verification passed as part of the final tranche run:

- `pytest tests/unit/test_prompt_normalizer.py tests/unit/test_prompt_deduper.py tests/unit/test_sdxl_prompt_optimizer.py -q`
- result: `20 passed in 0.33s`

Additional adjacent validation was attempted:

- `pytest tests/unit/test_prompt_optimizer_service.py tests/integration/test_prompt_optimizer_payload_integration.py tests/pipeline/test_executor_prompt_optimizer.py -q`
- unit and integration slices passed, but the pipeline slice failed due runtime
  admission poisoning in the current environment rather than prompt-optimizer
  assertions
