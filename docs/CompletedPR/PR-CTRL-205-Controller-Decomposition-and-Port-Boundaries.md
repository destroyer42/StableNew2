# PR-CTRL-205 - Controller Decomposition and Port Boundaries

Status: Completed 2026-03-18

## Summary

This PR extracts the queue-run bridge out of `AppController` and the
preview-to-queue submission bridge out of `PipelineController`.

The runtime behavior stays the same:

`AppController -> PipelineController -> JobService Queue -> Runner`

But the ownership is no longer concentrated entirely inside the two controller
monoliths.

## What Changed

### 1. AppController run submission moved into a dedicated service

New file:

- [run_submission_service.py](/c:/Users/rob/projects/StableNew/src/controller/app_controller_services/run_submission_service.py)

The new `QueueRunSubmissionService` owns:

- queue-only run-mode normalization
- run-config assembly for queue-backed execution
- the bridge from AppController to `PipelineController.start_pipeline(...)`

[app_controller.py](/c:/Users/rob/projects/StableNew/src/controller/app_controller.py) now delegates:

- `start_run_v2()`
- `_ensure_run_mode_default()`
- `_build_run_config()`
- `_start_run_v2()`

to the extracted service instead of carrying the full bridge logic inline.

### 2. PipelineController preview submission moved into a dedicated service

New file:

- [pipeline_submission_service.py](/c:/Users/rob/projects/StableNew/src/controller/pipeline_submission_service.py)

The new `PipelinePreviewSubmissionService` owns:

- converting preview NJRs into queue `Job` instances
- attaching payload/run snapshots for queue execution
- submitting preview jobs onto the current `JobService`

[pipeline_controller.py](/c:/Users/rob/projects/StableNew/src/controller/pipeline_controller.py) now delegates:

- `_to_queue_job(...)`
- `_submit_preview_jobs_for_run(...)`

to the extracted service.

### 3. The services are lazy-bound to current controller state

The test harnesses in this repo sometimes replace controller internals after
construction, especially fake `JobService` instances.

To keep those harnesses stable while still decomposing the controllers, both
services are now obtained lazily from the current controller state rather than
being permanently bound once in `__init__`.

This preserves testability and avoids stale references while still moving the
logic out of the controller classes.

## Impact

This PR reduces live controller bulk and makes the submission seams explicit:

- `app_controller.py`: about `6245` -> `5587` lines
- `pipeline_controller.py`: about `1792` -> `1566` lines

It does not attempt the full controller breakup in one PR. This slice targets
the highest-value seam first: run submission and preview submission.

## Verification

Passed:

- `pytest tests/controller/test_app_controller_pipeline_bridge.py tests/controller/test_app_controller_run_bridge_v2.py tests/controller/test_app_controller_run_mode_defaults.py tests/controller/test_app_controller_pipeline_integration.py tests/controller/test_app_controller_start_run_shim.py tests/controller/test_app_controller_lora_runtime.py tests/controller/test_pipeline_controller_run_modes_v2.py tests/pipeline/test_run_modes.py tests/journeys/test_v2_full_pipeline_journey.py tests/journey/test_phase1_pipeline_journey_v2.py tests/system/test_architecture_enforcement_v2.py -q`
- `pytest --collect-only -q` -> `2339 collected / 1 skipped`
- `python -m compileall src/controller/app_controller.py src/controller/pipeline_controller.py src/controller/app_controller_services/run_submission_service.py src/controller/pipeline_submission_service.py tests/controller/test_app_controller_run_bridge_v2.py tests/controller/test_pipeline_controller_run_modes_v2.py tests/journeys/test_v2_full_pipeline_journey.py tests/journey/test_phase1_pipeline_journey_v2.py`

## Deferred Debt and Future PR Owners

This PR intentionally leaves several follow-on items for their proper owners:

- `submit_direct()` compatibility shim in [job_service.py](/c:/Users/rob/projects/StableNew/src/controller/job_service.py)
  Future owner: `PR-POLISH-214`
- remaining archive DTO imports in active/non-canonical tests
  Future owner: `PR-TEST-211`
- residual `PipelineConfigPanel` naming/shim history in GUI surfaces
  Future owner: `PR-GUI-213`
- further controller size reduction beyond the submission-port slice
  Future owners: `PR-GUI-213` and `PR-POLISH-214`

Those mappings are also recorded in the active migration backlog:

- [MIGRATION_CLOSURE_EXECUTABLE_BACKLOG_v2.6-1.md](/c:/Users/rob/projects/StableNew/docs/PR_Backlog/MIGRATION_CLOSURE_EXECUTABLE_BACKLOG_v2.6-1.md)
