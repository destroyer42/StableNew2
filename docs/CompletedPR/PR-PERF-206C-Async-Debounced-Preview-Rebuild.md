# PR-PERF-206C - Async Debounced Preview Rebuild

Status: Completed 2026-03-18

## Summary

This PR keeps preview generation authoritative while moving the heavy rebuild
off the UI thread.

The goal is not to change preview semantics. The goal is to stop repeated
add-to-job operations from blocking the interface while preview NJRs are being
rebuilt.

## Runtime Changes

### 1. AppController preview refresh now applies asynchronously

[app_controller.py](/c:/Users/rob/projects/StableNew/src/controller/app_controller.py)
now routes preview-dirty work through `_refresh_preview_from_state_async()`.

Instead of invoking a synchronous controller refresh, the async path:

- increments a request id
- computes preview records on a worker thread
- applies results on the main thread
- discards stale results if a newer request already superseded them

### 2. Add-to-job no longer forces synchronous preview rebuild

`add_single_prompt_to_draft()` now marks preview state dirty and lets the async
refresh path handle the rebuild, instead of immediately blocking the UI on a
full preview recomputation.

### 3. Final state remains authoritative

Only the newest request id is allowed to write preview results back into
`AppState.preview_jobs`.

That preserves correctness under repeated add/remove/edit activity while still
allowing work to be computed off-thread.

## Verification

Passed:

- `pytest tests/controller/test_app_controller_pipeline_bridge.py tests/controller/test_app_controller_run_bridge_v2.py tests/controller/test_app_controller_pipeline_integration.py -q`
- `python -m compileall src/controller/app_controller.py tests/controller/test_app_controller_pipeline_bridge.py`

## Combined Perf Verification

The full touched perf surface also passed together:

- `pytest tests/pipeline/test_run_modes.py tests/controller/test_app_controller_run_bridge_v2.py tests/controller/test_app_controller_pipeline_integration.py tests/controller/test_job_service_unit.py tests/controller/test_pipeline_preview_to_queue_v2.py tests/controller/test_app_controller_pipeline_bridge.py tests/pipeline/test_prompt_pack_job_builder.py tests/controller/test_app_controller_add_to_queue_v2.py -q`

## Follow-On

This is a UI-path performance hardening slice. It does not replace the larger
platform polish pass still owned by `PR-POLISH-214`.
