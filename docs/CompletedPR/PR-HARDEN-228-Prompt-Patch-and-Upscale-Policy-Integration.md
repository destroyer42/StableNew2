# PR-HARDEN-228 - Prompt Patch and Upscale Policy Integration

Status: Completed 2026-03-20

## Summary

This PR completed the runtime-facing adaptive-refinement rollout for prompt
patching and bounded upscale policy application without widening the contract
surface. StableNew now applies deterministic stage-scoped text-token patches
inside executor-owned logic, carries the same canonical provenance through
manifests and embedded image metadata, and supports a narrow allowlist of
upscale overrides under `mode="full"`.

## Delivered

- added the deterministic patch helper in `src/refinement/prompt_patcher.py`
- extended `src/refinement/refinement_policy_registry.py` so full-mode decision
  bundles can emit bounded `prompt_patch` and upscale override payloads
- updated `src/pipeline/pipeline_runner.py` so full-mode upscale decisions are
  built per image, copied into per-image stage config, and recorded in the
  canonical `adaptive_refinement.image_decisions` list
- updated `src/pipeline/executor.py` so `txt2img`, `img2img`, `adetailer`, and
  `upscale` apply prompt patches before existing downstream processing and
  persist `prompt_patch_provenance` inside the same canonical carrier
- preserved v1 safety limits by ignoring LoRA tags, embedding references,
  textual inversion names, and weighted syntax inside prompt patches

## Key Files

- `src/refinement/prompt_patcher.py`
- `src/refinement/refinement_policy_registry.py`
- `src/pipeline/pipeline_runner.py`
- `src/pipeline/executor.py`
- `tests/refinement/test_prompt_patcher.py`
- `tests/pipeline/test_executor_prompt_optimizer.py`
- `tests/pipeline/test_pipeline_runner.py`
- `tests/pipeline/test_executor_refinement_manifest.py`

## Tests

Focused verification passed:

- `pytest tests/refinement/test_prompt_patcher.py tests/pipeline/test_executor_prompt_optimizer.py tests/pipeline/test_pipeline_runner.py tests/pipeline/test_executor_refinement_manifest.py tests/pipeline/test_executor_adetailer.py -q`
- result: `31 passed`
- `python -m compileall src/refinement src/pipeline tests/refinement tests/pipeline`
- `pytest --collect-only -q -rs` -> `2579 collected / 0 skipped`

## Documentation Updates

Bookkeeping closure recorded in:

- `docs/REFINEMENT_POLICY_SCHEMA_v1.md`
- `docs/Image_Metadata_Contract_v2.6.md`
- `docs/StableNew Roadmap v2.6.md`
- `docs/PR_Backlog/ADAPTIVE_REFINEMENT_EXECUTABLE_ROADMAP_v2.6.md`

## Deferred Debt

Intentionally deferred:

- learning-loop and recommendation-aware evaluation of refinement behavior
  Future owner: `PR-HARDEN-229`
- any GUI exposure for adaptive-refinement controls
  Future owner: later GUI follow-on after the adaptive series stabilizes
