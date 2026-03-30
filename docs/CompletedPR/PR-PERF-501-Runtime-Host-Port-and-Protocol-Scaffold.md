# PR-PERF-501 - Runtime Host Port and Protocol Scaffold

Status: Completed 2026-03-30

## Summary

This PR introduced the first explicit runtime-host seam without changing
production runtime ownership.

- added a new `src/runtime_host/` package for protocol envelopes, host-port
  typing, and the local adapter over the existing `JobService`
- rewired `AppController`, `PipelineController`, and `build_v2_app(...)` to
  accept the runtime-host seam while preserving local queue-first behavior
- moved additional controller helper language toward runtime-host terminology
  while keeping older `job_service` helper aliases for compatibility

## Delivered

### 1. Runtime-host contract and local adapter

- added protocol name/version constants and JSON-safe payload normalization in
  `src/runtime_host/messages.py`
- added `RuntimeHostPort` plus runtime-host event constants in
  `src/runtime_host/port.py`
- added `LocalRuntimeHostAdapter`, `coerce_runtime_host(...)`, and
  `build_local_runtime_host(...)` in `src/runtime_host/local_adapter.py`

### 2. Controller and bootstrap rewiring

- `AppController` now accepts `runtime_host` and keeps `job_service` as a
  compatibility alias to the injected or locally built runtime host
- `PipelineController` now exposes `get_runtime_host()` as the primary seam and
  retains `get_job_service()` as a compatibility alias
- `build_v2_app(...)` now resolves `runtime_host` or `job_service` through the
  shared runtime-host coercion path

### 3. Compatibility-preserving cleanup

- updated selected controller helper names, shutdown flow, and docstrings to use
  runtime-host terminology where safe
- preserved older helper aliases so existing controller tests and stubs do not
  need an immediate rename sweep

## Validation

Passed:

- `c:/Users/rob/projects/StableNew/.venv/Scripts/python.exe -m pytest tests/runtime_host/test_protocol_and_local_adapter.py tests/controller/test_runtime_host_port_wiring.py tests/controller/test_core_run_path_v2.py tests/controller/test_app_controller_queue_source.py -q`
- `c:/Users/rob/projects/StableNew/.venv/Scripts/python.exe -m pytest tests/controller/test_app_controller_diagnostics.py tests/controller/test_queue_callback_gui_thread_marshaling.py tests/controller/test_job_history_controller_v2.py -q`
- `c:/Users/rob/projects/StableNew/.venv/Scripts/python.exe -m pytest tests/controller/test_app_controller_add_to_queue_v2.py tests/controller/test_app_controller_pipeline_bridge.py tests/controller/test_app_controller_pipeline_draft_v2.py tests/controller/test_app_controller_pipeline_integration.py tests/controller/test_app_controller_queue_restore.py tests/controller/test_app_controller_run_bridge_v2.py tests/controller/test_app_controller_run_now_bridge.py tests/controller/test_app_controller_service_contracts.py tests/controller/test_app_controller_shutdown_v2.py tests/controller/test_app_controller_njr_exec.py tests/controller/test_pipeline_controller_queue_mode.py tests/controller/test_pipeline_controller_run_modes_v2.py tests/controller/test_pipeline_controller_history_refresh_v2.py tests/controller/test_pipeline_controller_job_specs_v2.py tests/controller/test_pipeline_controller_jobbuilder_integration_v2.py tests/controller/test_pipeline_controller_webui_gating.py -q`
- `c:/Users/rob/projects/StableNew/.venv/Scripts/python.exe -m pytest tests/controller/test_app_controller_run_mode_defaults.py -q`
- `c:/Users/rob/projects/StableNew/.venv/Scripts/python.exe -m pytest tests/journeys/test_jt06_prompt_pack_queue_run.py -q`

Validation notes:

- `tests/journeys/test_jt03_txt2img_pipeline_run.py` still expects
  `start_run_v2()` to surface `run_mode == "direct"`, but
  `tests/controller/test_app_controller_run_mode_defaults.py` continues to
  codify the queue-first `start_run_v2()` default in current repo truth.
- `tests/journeys/test_v2_full_pipeline_journey.py` hit local Tk installation
  issues in the current workstation environment and did not provide a stable
  signal for this PR.

## Follow-On

- `PR-PERF-502` is now the active next step for runtime isolation.
- This PR intentionally does not move queue, runner, history, or backend
  lifecycle ownership out of process yet.