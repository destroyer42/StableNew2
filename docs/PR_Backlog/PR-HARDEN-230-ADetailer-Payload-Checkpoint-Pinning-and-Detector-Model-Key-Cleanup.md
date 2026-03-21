# PR-HARDEN-230 - ADetailer Payload Checkpoint Pinning and Detector Model Key Cleanup

Status: Implemented 2026-03-20
Priority: HIGH
Effort: SMALL
Phase: Image Pipeline Hardening
Date: 2026-03-20

## Context & Motivation

Current repo truth: the runner already pins downstream image stages to the NJR
base model, but ADetailer still relies too heavily on ambient WebUI state once
execution reaches the executor. The canonical config merger also still writes a
generic ADetailer `model` key even though that field is detector-facing, not SD
checkpoint-facing.

This PR exists now because users are still seeing apparent checkpoint drift
between `txt2img`, `adetailer`, and later image stages.

References:

- `docs/ARCHITECTURE_v2.6.md`
- `docs/Image_Metadata_Contract_v2.6.md`
- `docs/StableNew Roadmap v2.6.md`
- `docs/CompletedPR/PR-HARDEN-227-Safe-ADetailer-Adaptive-Policy-Application.md`

## Goals & Non-Goals

### Goals

1. Force the requested SD checkpoint into the actual ADetailer/img2img payload.
2. Make img2img, ADetailer, and upscale manifests prefer requested stage config
   over ambient WebUI state when recording model provenance.
3. Remove the ambiguous generic ADetailer `model` alias from canonical config
   merging.
4. Add regression coverage for stage pinning and manifest provenance.

### Non-Goals

1. Do not add per-stage checkpoint GUI controls in this PR.
2. Do not change PromptPack, NJR, queue, or runner architecture.
3. Do not change ADetailer detector selection semantics beyond key cleanup.

## Guardrails

1. NJR remains the only outer job contract.
2. The runner may be touched only for regression verification, not for new
   architectural behavior.
3. GUI files are out of scope.
4. Do not introduce a compatibility shim that keeps both ADetailer detector
   keys active for write paths.

## Allowed Files

### Files to Create

- `docs/CompletedPR/PR-HARDEN-230-ADetailer-Payload-Checkpoint-Pinning-and-Detector-Model-Key-Cleanup.md`

### Files to Modify

- `src/pipeline/executor.py`
- `src/pipeline/config_merger_v2.py`
- `tests/pipeline/test_executor_adetailer.py`
- `tests/pipeline/test_executor_refinement_manifest.py`
- `tests/pipeline/test_pipeline_batch_processing.py`
- `tests/pipeline/test_config_merger_v2.py`
- `docs/StableNew Roadmap v2.6.md`
- `docs/DOCS_INDEX_v2.6.md`
- `docs/PR_Backlog/PR-HARDEN-230-ADetailer-Payload-Checkpoint-Pinning-and-Detector-Model-Key-Cleanup.md`

### Forbidden Files

- `src/controller/**`
- `src/gui/**`
- `src/video/**`
- `src/pipeline/job_models_v2.py`
- `src/pipeline/config_contract_v26.py`

## Implementation Plan

1. Harden the executor ADetailer request path in `src/pipeline/executor.py`.
   Add explicit per-request checkpoint fields to the ADetailer payload and make
   manifest model precedence prefer requested config first.
2. Remove the generic ADetailer `model` write-path alias in
   `src/pipeline/config_merger_v2.py`, preserving `adetailer_model` as the
   canonical detector key.
3. Add focused regressions in executor and runner-adjacent tests proving the
   base model remains pinned through `txt2img`, `adetailer`, and `upscale`.
4. Record completion and roadmap status in docs.

## Testing Plan

### Unit Tests

- `pytest tests/pipeline/test_config_merger_v2.py tests/pipeline/test_executor_adetailer.py -q`

### Integration Tests

- `pytest tests/pipeline/test_executor_refinement_manifest.py tests/pipeline/test_pipeline_batch_processing.py -q`

### Journey or Smoke Coverage

- one mocked txt2img -> adetailer -> upscale path verifying manifest/config
  model consistency

### Manual Verification

1. Run a normal image job with ADetailer and inspect all three manifests.
2. Confirm the base model remains unchanged unless an explicit future override
   exists.

## Verification Criteria

### Success Criteria

1. ADetailer payload includes explicit checkpoint pinning when a base model is
   requested.
2. Manifest model provenance prefers requested stage config over ambient WebUI
   state.
3. Canonical config merging no longer writes `adetailer.model`.

### Failure Criteria

1. Detector selection stops working because `adetailer_model` was lost.
2. Manifest model values still drift when WebUI reports a different current
   model.
3. Hidden stage config can still override the NJR base model without an
   explicit future UI surface.

## Risk Assessment

### Low-Risk Areas

- config merger key cleanup

### Medium-Risk Areas With Mitigation

- ADetailer payload field compatibility
  - Mitigation: keep changes additive and covered by executor tests

### High-Risk Areas With Mitigation

- writing the wrong manifest model even when generation is correct
  - Mitigation: use requested config as first precedence in metadata

### Rollback Plan

Revert payload pinning and restore previous manifest precedence while keeping
the regression tests for investigation.

## Tech Debt Analysis

### Debt Removed

- ambiguous detector-vs-checkpoint `model` usage in ADetailer config
- weak ADetailer checkpoint pinning at the request layer

### Debt Intentionally Deferred

- explicit per-stage checkpoint GUI controls
  - Owner: follow-on UX planning

## Documentation Updates

- update `docs/StableNew Roadmap v2.6.md`
- update `docs/DOCS_INDEX_v2.6.md`
- add completion record in `docs/CompletedPR/`

## Dependencies

### Internal Module Dependencies

- `src/pipeline/executor.py`
- `src/pipeline/config_merger_v2.py`

### External Tools or Runtimes

- WebUI img2img / ADetailer API compatibility

## Approval & Execution

Planner: ChatGPT/Codex
Executor: Codex
Reviewer: Human
Approval Status: Approved

## Next Steps

- `PR-HARDEN-231-Output-Root-Normalization-and-Route-Classification-Audit`
- `PR-GUI-232-Pack-Selector-Cleanup-and-Real-Pack-Refresh-Discovery`

## Post-Implementation Summary

- delivered explicit checkpoint pinning in the ADetailer payload path in
  `src/pipeline/executor.py`
- made img2img, ADetailer, and upscale manifests prefer requested stage config
  over ambient WebUI state for model provenance
- removed the generic write-path `adetailer.model` alias from
  `src/pipeline/config_merger_v2.py` while preserving `adetailer_model`
- added focused regressions in
  `tests/pipeline/test_config_merger_v2.py`,
  `tests/pipeline/test_executor_adetailer.py`,
  `tests/pipeline/test_executor_refinement_manifest.py`, and
  `tests/pipeline/test_pipeline_batch_processing.py`
- verification passed:
  `pytest tests/pipeline/test_config_merger_v2.py tests/pipeline/test_executor_adetailer.py tests/pipeline/test_executor_refinement_manifest.py tests/pipeline/test_pipeline_batch_processing.py -q`
  -> `43 passed`
- `python -m compileall src/pipeline/config_merger_v2.py src/pipeline/executor.py tests/pipeline/test_config_merger_v2.py tests/pipeline/test_executor_adetailer.py tests/pipeline/test_executor_refinement_manifest.py`
- `pytest --collect-only -q -rs` -> `2588 collected / 0 skipped`

