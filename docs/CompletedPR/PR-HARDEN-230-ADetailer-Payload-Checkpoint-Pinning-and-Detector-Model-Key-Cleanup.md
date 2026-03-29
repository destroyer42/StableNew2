# PR-HARDEN-230 - ADetailer Payload Checkpoint Pinning and Detector Model Key Cleanup

Status: Completed 2026-03-20

## Summary

This PR removed the remaining ambiguous checkpoint behavior in the ADetailer
path. StableNew now forces the requested SD checkpoint into the actual
ADetailer payload, records model provenance from the requested stage config
instead of ambient WebUI state, and stops writing the detector-facing ADetailer
model into a generic `model` config key.

## Delivered

- updated `src/pipeline/executor.py` so the ADetailer payload carries explicit
  checkpoint override fields and manifests prefer requested stage config for
  model provenance
- hardened img2img and upscale manifest model precedence so hidden ambient
  WebUI state does not override requested config in recorded metadata
- updated `src/pipeline/config_merger_v2.py` to canonicalize legacy ADetailer
  detector config into `adetailer_model` and stop writing `adetailer.model`
- added focused regressions for merger canonicalization, ADetailer payload
  pinning, manifest precedence, and downstream-stage base-model pinning

## Key Files

- `src/pipeline/executor.py`
- `src/pipeline/config_merger_v2.py`
- `tests/pipeline/test_config_merger_v2.py`
- `tests/pipeline/test_executor_adetailer.py`
- `tests/pipeline/test_executor_refinement_manifest.py`
- `tests/pipeline/test_pipeline_batch_processing.py`

## Tests

Focused verification passed:

- `pytest tests/pipeline/test_config_merger_v2.py tests/pipeline/test_executor_adetailer.py tests/pipeline/test_executor_refinement_manifest.py tests/pipeline/test_pipeline_batch_processing.py -q`
- result: `43 passed`
- `python -m compileall src/pipeline/config_merger_v2.py src/pipeline/executor.py tests/pipeline/test_config_merger_v2.py tests/pipeline/test_executor_adetailer.py tests/pipeline/test_executor_refinement_manifest.py`
- `pytest --collect-only -q -rs` -> `2588 collected / 0 skipped`

## Documentation Updates

Bookkeeping closure recorded in:

- `docs/StableNew Roadmap v2.6.md`
- `docs/DOCS_INDEX_v2.6.md`

## Deferred Debt

Intentionally deferred:

- output-root normalization and route-classification cleanup
  Future owner: `PR-HARDEN-231`
- PromptPack selector and refresh UX cleanup
  Future owner: `PR-GUI-232`
