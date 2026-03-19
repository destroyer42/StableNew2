# PR-CONFIG-206 — Canonical Config Unification

Status: Completed 2026-03-18

## Purpose

Define and implement one canonical config layering model for the live v2.6
runtime:

- `intent_config`
- normalized execution config
- `backend_options`

This PR makes those layers explicit in code, NJRs, queue snapshots, and
submission metadata without introducing a second job model or a second runtime
path.

## Runtime Changes

### 1. Canonical config-layer contract

Added [config_contract_v26.py](/c:/Users/rob/projects/StableNew/src/pipeline/config_contract_v26.py).

This module defines:

- `CONFIG_CONTRACT_SCHEMA_V26 = "stablenew.config.v2.6"`
- `CanonicalConfigLayers`
- `attach_config_layers(...)`
- `build_config_layers(...)`
- `extract_execution_config(...)`
- `derive_backend_options(...)`

The contract formalizes:

- intent metadata as non-executable submission context
- execution config as the only stage-ready config layer
- backend-local options as separate backend-owned metadata

### 2. Normalizer and builder alignment

[config_normalizer.py](/c:/Users/rob/projects/StableNew/src/pipeline/config_normalizer.py)
now extracts the execution layer before normalizing, so layered payloads and
legacy flat execution dicts both normalize through one code path.

[job_builder_v2.py](/c:/Users/rob/projects/StableNew/src/pipeline/job_builder_v2.py)
now stamps NJRs built from `PipelineRunRequest` with canonical `intent_config`
and derived `backend_options`.

[prompt_pack_job_builder.py](/c:/Users/rob/projects/StableNew/src/pipeline/prompt_pack_job_builder.py)
now stamps prompt-pack NJRs with canonical intent and backend metadata as part
of the normal build path.

### 3. NJR and snapshot persistence

[job_models_v2.py](/c:/Users/rob/projects/StableNew/src/pipeline/job_models_v2.py)
now persists:

- `intent_config`
- `backend_options`
- `config_layers`

in queue snapshots produced by `NormalizedJobRecord.to_queue_snapshot()`.

[snapshot_builder_v2.py](/c:/Users/rob/projects/StableNew/src/utils/snapshot_builder_v2.py)
now writes the same canonical config-layer metadata into replay/history
snapshots and restores it during NJR hydration.

### 4. Queue submission metadata

[run_submission_service.py](/c:/Users/rob/projects/StableNew/src/controller/app_controller_services/run_submission_service.py)
now emits queue submission metadata with canonical `config_layers` attached,
while preserving the legacy top-level keys that active controller tests and
queue metadata still rely on.

## Verification

Passed:

- `pytest tests/pipeline/test_config_contract_v26.py tests/pipeline/test_job_builder_v2.py tests/pipeline/test_prompt_pack_job_builder.py tests/controller/test_app_controller_run_bridge_v2.py tests/utils/test_snapshot_builder_v2.py -q`
- `pytest tests/controller/test_app_controller_pipeline_bridge.py tests/controller/test_app_controller_run_mode_defaults.py tests/controller/test_app_controller_pipeline_integration.py tests/controller/test_pipeline_controller_run_modes_v2.py tests/pipeline/test_run_modes.py tests/controller/test_job_service_normalized_v2.py -q`
- `pytest --collect-only -q` -> `2342 collected / 1 skipped`
- `python -m compileall ...` on the touched pipeline/controller/utils modules and tests

## Documentation Updates

Updated:

- [ARCHITECTURE_v2.6.md](/c:/Users/rob/projects/StableNew/docs/ARCHITECTURE_v2.6.md)
- [MIGRATION_CLOSURE_EXECUTABLE_BACKLOG_v2.6-1.md](/c:/Users/rob/projects/StableNew/docs/PR_Backlog/MIGRATION_CLOSURE_EXECUTABLE_BACKLOG_v2.6-1.md)

## Outstanding Debt

Intentionally deferred:

- `AppStateV2.run_config` is still a dict-shaped GUI façade over the canonical
  config layers.
  Future owner: `PR-GUI-213`
- richer backend-specific config compilation is still future work for the Comfy
  workflow/compiler/runtime tranche.
  Future owners: `PR-COMFY-208`, `PR-COMFY-209`, `PR-COMFY-210`

## Next PR

Next planned PR: `PR-VIDEO-207`
