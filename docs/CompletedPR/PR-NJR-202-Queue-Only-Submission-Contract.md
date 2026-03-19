# PR-NJR-202: Queue-Only Submission Contract

## Status

Completed on 2026-03-18.

## Purpose

Collapse fresh runtime submission onto the queue path so StableNew no longer has
an active `DIRECT` execution mode for normal image/video job submission.

## What Changed

### Runtime and request normalization

- [src/pipeline/job_requests_v2.py](/c:/Users/rob/projects/StableNew/src/pipeline/job_requests_v2.py)
  now coerces legacy `run_mode="direct"` request data to `queue` during
  construction and deserialization.
- [src/pipeline/run_config.py](/c:/Users/rob/projects/StableNew/src/pipeline/run_config.py)
  now defaults `RunConfig.run_mode` to `queue`.
- [src/utils/prompt_packs.py](/c:/Users/rob/projects/StableNew/src/utils/prompt_packs.py)
  now defaults prompt-pack and manual run configs to `queue`.
- [src/pipeline/cli_njr_builder.py](/c:/Users/rob/projects/StableNew/src/pipeline/cli_njr_builder.py)
  now emits CLI NJRs with `run_mode="QUEUE"`.

### Controller and submission path

- [src/controller/app_controller.py](/c:/Users/rob/projects/StableNew/src/controller/app_controller.py)
  now treats both `Run` and `Run Now` as queue-backed submission entrypoints.
  The live `RunMode` enum is queue-only, and pipeline state is normalized to
  `queue`.
- [src/controller/pipeline_controller.py](/c:/Users/rob/projects/StableNew/src/controller/pipeline_controller.py)
  now normalizes all fresh preview submission to `queue`, even when older call
  sites still pass `run_mode="direct"`.
- [src/controller/job_service.py](/c:/Users/rob/projects/StableNew/src/controller/job_service.py)
  now coerces legacy direct jobs to queued jobs inside
  `submit_job_with_run_mode()`. The old `submit_direct()` surface is reduced to
  a compatibility shim that enqueues queue-backed work instead of executing a
  second synchronous path.

### GUI defaults

- [src/gui/state.py](/c:/Users/rob/projects/StableNew/src/gui/state.py)
  now defaults `PipelineState.run_mode` to `queue`.
- [src/gui/sidebar_panel_v2.py](/c:/Users/rob/projects/StableNew/src/gui/sidebar_panel_v2.py)
  no longer offers a live `Direct` runtime selector and now presents queue-only
  execution in the sidebar.

## Tests Updated

- [tests/controller/test_app_controller_pipeline_bridge.py](/c:/Users/rob/projects/StableNew/tests/controller/test_app_controller_pipeline_bridge.py)
- [tests/controller/test_app_controller_run_mode_defaults.py](/c:/Users/rob/projects/StableNew/tests/controller/test_app_controller_run_mode_defaults.py)
- [tests/controller/test_app_controller_run_bridge_v2.py](/c:/Users/rob/projects/StableNew/tests/controller/test_app_controller_run_bridge_v2.py)
- [tests/controller/test_app_to_pipeline_run_bridge_v2.py](/c:/Users/rob/projects/StableNew/tests/controller/test_app_to_pipeline_run_bridge_v2.py)
- [tests/controller/test_pipeline_controller_run_modes_v2.py](/c:/Users/rob/projects/StableNew/tests/controller/test_pipeline_controller_run_modes_v2.py)
- [tests/pipeline/test_run_modes.py](/c:/Users/rob/projects/StableNew/tests/pipeline/test_run_modes.py)
- [tests/cli/test_cli_njr_execution.py](/c:/Users/rob/projects/StableNew/tests/cli/test_cli_njr_execution.py)
- [tests/gui_v2/test_pipeline_dropdown_refresh_v2.py](/c:/Users/rob/projects/StableNew/tests/gui_v2/test_pipeline_dropdown_refresh_v2.py)

## Verification

Passed:

- `pytest tests/controller/test_app_controller_pipeline_bridge.py tests/controller/test_app_controller_run_mode_defaults.py tests/controller/test_app_controller_run_bridge_v2.py tests/controller/test_app_to_pipeline_run_bridge_v2.py tests/controller/test_pipeline_controller_run_modes_v2.py tests/pipeline/test_run_modes.py tests/cli/test_cli_njr_execution.py tests/gui_v2/test_pipeline_dropdown_refresh_v2.py -q`
- `pytest --collect-only -q` -> `2334 collected / 1 skipped`
- `python -m compileall` on the touched controller, pipeline, gui, and utils files

## Boundary and Follow-On

This PR removes the live fresh-runtime `DIRECT` path, but it does not yet
delete every legacy compatibility symbol or every older test that still uses the
word `direct`.

Deferred to later migration tranches:

1. deleting remaining archive/compat-only surfaces entirely
2. migrating older journey/integration/queue tests that still encode historical
   direct-mode expectations
3. one-time persisted queue/history migration for older serialized shapes

One unrelated existing failure surfaced during wider exploration:

- [tests/queue/test_job_history_store.py](/c:/Users/rob/projects/StableNew/tests/queue/test_job_history_store.py)
  currently fails because `JSONLJobHistoryStore.record_job_submission()` writes
  asynchronously and `record_status_change()` immediately assumes the
  submission entry is already readable. That is outside the queue-only cut and
  should be handled as a separate history-store fix.
