# PR-PIPE-063: Canonical Stage Contract Preferred-Flow Normalization

## Summary

Normalize the runtime/test contract around the actual preferred still-image flow:

`txt2img -> optional img2img -> optional adetailer -> optional final upscale`

Refiner and hires remain supported, but as advanced `txt2img` metadata only. They are
not separate stages and should not bleed into later preferred-flow stages.

## Allowed Files

- `src/pipeline/stage_sequencer.py`
- `src/pipeline/stage_models.py`
- `src/pipeline/payload_builder.py`
- `src/utils/config.py`
- `tests/pipeline/test_stage_sequencer_plan_builder.py`
- `tests/pipeline/test_stage_sequencing.py`
- `tests/api/test_sdxl_payloads.py`
- `tests/unit/test_config_presets_v2.py`
- `docs/PR_MAR26/PR-PIPE-063-Canonical-Stage-Contract-Preferred-Flow-Normalization.md`

## Implementation

1. Keep the canonical stage order unchanged: `txt2img -> img2img -> adetailer -> upscale -> animatediff`.
2. Tighten `StageMetadata` construction so refiner/hires metadata stays on canonical `txt2img` stages instead of leaking into `img2img`, `adetailer`, or `upscale`.
3. Update payload-builder and config docstrings/comments so the preferred still-image flow is explicit and refiner/hires are framed as advanced txt2img metadata.
4. Update tests to assert:
   - the preferred stage chain remains `txt2img -> optional img2img -> optional adetailer -> optional upscale`
   - refiner/hires metadata does not bleed into later stages
   - default config keeps only `txt2img` enabled in the happy path

## Verification

- Targeted pytest on touched pipeline/api/unit suites
- `pytest --collect-only -q`
- `python -m compileall` on touched modules/tests

## Rollback

Revert the touched stage contract, config-commentary, and test files together. No schema
or queue/history changes are included in this PR.
