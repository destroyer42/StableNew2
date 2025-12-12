# PR9 — Randomization Refinement & Prompt Sanitization

## Goals

1. Ensure the “Preview Payload (Dry Run)” and the live pipeline use exactly the same prompt randomization path.
2. Prevent leftover `[[matrix]]` slots and `__wildcard__` markers from ever reaching SD WebUI.
3. Surface matrix configuration details (mode, slots, limits) in the logs so large fan-outs are obvious before a run.

## Implementation Notes

- Added a helper `sanitize_prompt()` in `src/gui/main_window.py` that strips matrix slots and wildcard tokens and normalises whitespace.
- `_run_full_pipeline()` now:
  - Applies `PromptRandomizer.generate()` before building stage variants.
  - Injects the sanitised prompt (and optional per-prompt negative) back into the effective `txt2img` config before execution.
  - Logs a hint when randomisation only produced a single variant so users can fix their rules.
- The txt2img-only quick action mirrors the same logic so “single prompt” workflows stay in sync.
- `PromptRandomizer` emits a matrix summary line describing the mode and number of precomputed combinations, and warns when limit=0 creates a massive grid.

## Testing

- Added `tests/gui/test_prompt_sanitization.py` to exercise the new helper and make sure both matrix slots and wildcard tokens are removed.
- Existing randomiser tests continue to run unchanged, providing coverage for fan-out vs sequential modes.

## User Impact

- Dry-run counts now match real pipeline output because they travel through the same sanitised prompt path.
- SD WebUI will no longer see raw placeholders, preventing confusing generations like “__mood__ warrior”.
- Large matrix runs emit log warnings (“limit is 0, combos=2048”) before the first request hits the API, reducing surprise timeouts.
