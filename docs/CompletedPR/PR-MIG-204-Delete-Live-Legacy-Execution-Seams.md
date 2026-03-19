# PR-MIG-204 - Delete Live Legacy Execution Seams

Status: Completed 2026-03-18

## Summary

This PR removes the remaining live runtime seams that kept legacy
`PipelineConfig`-style execution alive after the NJR and queue-first migrations.

The runtime now follows one active execution story:

`GUI/CLI/Reprocess/Learning -> NJR -> JobService Queue -> Runner -> Replay/Runner -> Artifacts/History`

## What Changed

### 1. Live archive imports were removed from runtime source

The live source no longer imports `src.controller.archive.pipeline_config_*`.

Primary runtime cuts:

- [src/controller/app_controller.py](/c:/Users/rob/projects/StableNew/src/controller/app_controller.py)
- [src/controller/pipeline_controller.py](/c:/Users/rob/projects/StableNew/src/controller/pipeline_controller.py)

`app_controller.py` now keeps only a small
`DeprecatedPipelineConfigSnapshot` dataclass for non-runtime helper/test
surfaces. Execution no longer depends on archive DTOs.

### 2. Legacy adapter and request flags were removed

- deleted [src/pipeline/legacy_njr_adapter.py](/c:/Users/rob/projects/StableNew/src/pipeline/legacy_njr_adapter.py)
- removed `allow_legacy_fallback` from [src/pipeline/job_requests_v2.py](/c:/Users/rob/projects/StableNew/src/pipeline/job_requests_v2.py)
- removed `PipelineRunMode.DIRECT` from [src/pipeline/job_requests_v2.py](/c:/Users/rob/projects/StableNew/src/pipeline/job_requests_v2.py)

Associated callsites were updated in:

- [src/controller/svd_controller.py](/c:/Users/rob/projects/StableNew/src/controller/svd_controller.py)
- [src/learning/execution_controller.py](/c:/Users/rob/projects/StableNew/src/learning/execution_controller.py)
- [src/pipeline/reprocess_builder.py](/c:/Users/rob/projects/StableNew/src/pipeline/reprocess_builder.py)

### 3. AppController no longer executes legacy pipeline-config paths

The deprecated runtime entrypoints now fail loudly or normalize to the queue path
instead of keeping a second execution model alive.

Key behavior changes:

- `on_run_clicked()` validates and routes to `start_run_v2()`
- `start_run()` normalizes to `start_run_v2()`
- `run_pipeline()` is retained only as a deprecated queue-backed shim
- `_run_pipeline_thread()` is retired and now raises if called
- `_execute_pipeline_via_runner()` and related pipeline-config runtime helpers stay disabled

This keeps older test/helper surfaces callable without allowing them to reopen a
real runtime seam.

### 4. PipelineController now treats queue/NJR as the only active runtime model

`pipeline_controller.py` no longer builds live archive configs through the
archive assembler. Queue submission is the only active execution path.

Additional cleanup:

- `_build_job()` now handles config-like mappings cleanly for metadata snapshots
- run mode normalization is queue-only at the controller boundary

### 5. Architecture enforcement and active tests were updated

Architecture enforcement now asserts that the legacy adapter module is gone and
that no live source file imports archive pipeline-config types:

- [tests/system/test_architecture_enforcement_v2.py](/c:/Users/rob/projects/StableNew/tests/system/test_architecture_enforcement_v2.py)

Active tests touched to match queue-first/NJR-first truth:

- [tests/controller/test_app_controller_pipeline_integration.py](/c:/Users/rob/projects/StableNew/tests/controller/test_app_controller_pipeline_integration.py)
- [tests/controller/test_app_controller_start_run_shim.py](/c:/Users/rob/projects/StableNew/tests/controller/test_app_controller_start_run_shim.py)
- [tests/pipeline/test_run_modes.py](/c:/Users/rob/projects/StableNew/tests/pipeline/test_run_modes.py)
- [tests/journeys/fakes/fake_pipeline_runner.py](/c:/Users/rob/projects/StableNew/tests/journeys/fakes/fake_pipeline_runner.py)
- [tests/journeys/test_v2_full_pipeline_journey.py](/c:/Users/rob/projects/StableNew/tests/journeys/test_v2_full_pipeline_journey.py)
- [tests/journey/test_phase1_pipeline_journey_v2.py](/c:/Users/rob/projects/StableNew/tests/journey/test_phase1_pipeline_journey_v2.py)

The journey tests were deliberately rewritten to assert deterministic queue
submission with the repo's `StubRunner` harness instead of relying on flaky
timing against a background worker.

## Verification

Passed:

- `pytest tests/system/test_architecture_enforcement_v2.py tests/controller/test_app_controller_pipeline_integration.py tests/controller/test_app_controller_start_run_shim.py tests/controller/test_app_controller_lora_runtime.py tests/controller/test_pipeline_controller_run_modes_v2.py tests/pipeline/test_run_modes.py tests/journeys/test_v2_full_pipeline_journey.py tests/journey/test_phase1_pipeline_journey_v2.py -q`
- `pytest --collect-only -q` -> `2339 collected / 1 skipped`
- `python -m compileall src/controller/app_controller.py src/controller/pipeline_controller.py src/pipeline/job_requests_v2.py src/controller/svd_controller.py src/learning/execution_controller.py src/pipeline/reprocess_builder.py tests/controller/test_app_controller_pipeline_integration.py tests/controller/test_app_controller_start_run_shim.py tests/pipeline/test_run_modes.py tests/journeys/test_v2_full_pipeline_journey.py tests/journey/test_phase1_pipeline_journey_v2.py tests/system/test_architecture_enforcement_v2.py`

Repo-wide grep check:

- `rg -n "from src\\.controller\\.archive|import src\\.controller\\.archive|legacy_njr_adapter|allow_legacy_fallback" src`
- remaining match is archive-internal only: [src/controller/archive/pipeline_config_assembler.py](/c:/Users/rob/projects/StableNew/src/controller/archive/pipeline_config_assembler.py)

## Remaining Debt After This PR

This PR intentionally does not consume the next migration slices.

Still outstanding:

- `submit_direct()` still exists in [src/controller/job_service.py](/c:/Users/rob/projects/StableNew/src/controller/job_service.py) as a queue-normalizing compatibility shim
- some non-canonical or quarantine-style tests still import archive `PipelineConfig` DTOs
- GUI shim surfaces still carry `PipelineConfigPanel` naming/history
- [src/controller/app_controller.py](/c:/Users/rob/projects/StableNew/src/controller/app_controller.py) and [src/controller/pipeline_controller.py](/c:/Users/rob/projects/StableNew/src/controller/pipeline_controller.py) remain oversized and are the next major structural debt target

Those are deferred to:

- `PR-CTRL-205`
- `PR-TEST-211`
- later GUI cleanup tranches
