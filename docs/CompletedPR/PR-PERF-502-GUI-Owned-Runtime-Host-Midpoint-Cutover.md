# PR-PERF-502 - GUI-Owned Runtime Host Midpoint Cutover

Status: Completed 2026-03-30

## Summary

This PR moved production runtime ownership out of the GUI process and into a
GUI-owned local child runtime host while preserving queue-only NJR execution.

- production startup now launches a bounded-handshake child runtime host before
  enabling runtime-backed actions
- production `AppController` and `PipelineController` now operate through the
  GUI-side runtime client rather than a same-process `JobService` path
- managed WebUI and Comfy lifecycle ownership moved into the child runtime host
- Debug Hub now shows runtime-host transport, protocol/version, host pid,
  startup or disconnect errors, and managed-runtime diagnostics
- shutdown and disconnect hardening now stop the child host deterministically
  and surface host-loss state in the GUI instead of silently freezing controls

## Delivered

### 1. Child runtime host production cutover

- added the GUI-owned child runtime host bootstrap, server, and client flow in
  `src/runtime_host/`
- updated `build_v2_app(...)` and `src/main.py` to launch the child host and
  fail fast on bounded handshake errors
- kept the local runtime-host adapter as DI-only and test-only after cutover

### 2. Host-owned runtime lifecycle and controller adoption

- moved `JobService`, queue, runner, history, watchdog, and managed WebUI/Comfy
  ownership into the child host
- updated controller run-preflight and WebUI launch/retry actions to call the
  host when transport is remote
- removed GUI-owned production WebUI/Comfy bootstrap scheduling from startup

### 3. Diagnostics and lifecycle hardening

- normalized runtime-host diagnostics in `AppController` and surfaced them in
  the Debug Hub diagnostics dashboard
- added managed-runtime diagnostics for WebUI and Comfy, including host pid,
  connection state, and startup-error visibility
- hardened runtime-host shutdown and disconnect handling so the GUI marks host
  loss explicitly and parent disconnect triggers host cleanup

## Validation

Passed:

- `c:/Users/rob/projects/StableNew/.venv/Scripts/python.exe -m pytest tests/runtime_host/test_child_runtime_host_server.py tests/runtime_host/test_protocol_and_local_adapter.py tests/controller/test_runtime_host_port_wiring.py tests/controller/test_pipeline_controller_webui_gating.py tests/controller/test_webui_lifecycle_ux_v2.py tests/controller/test_app_controller_diagnostics.py tests/app/test_bootstrap_webui_autostart.py tests/app/test_bootstrap_comfy_autostart.py tests/test_main_single_instance.py -q`
- `c:/Users/rob/projects/StableNew/.venv/Scripts/python.exe -m pytest tests/gui_v2/test_debug_hub_panel_v2.py tests/gui_v2/test_diagnostics_dashboard_v2.py tests/controller/test_app_controller_diagnostics.py -q`
- `c:/Users/rob/projects/StableNew/.venv/Scripts/python.exe -m pytest tests/runtime_host/test_child_runtime_host_client.py tests/runtime_host/test_child_runtime_host_server.py tests/controller/test_app_controller_shutdown_v2.py tests/controller/test_webui_lifecycle_ux_v2.py -q`

Validation notes:

- the focused diagnostics slice passed with one Tk-availability skip in
  `tests/gui_v2/test_diagnostics_dashboard_v2.py`, which is consistent with the
  repo's headless-safe GUI policy on this Windows workstation
- direct `pytest` in the configured `.venv` remained the reliable validation
  path for focused slices in this repository

## Follow-On

- midpoint soak validation is now the gating step before `PR-PERF-503`
- `PR-PERF-503` remains the next runtime-isolation PR, but it is blocked until
  the child-host midpoint proves materially improved GUI responsiveness without
  major queue, watchdog, or diagnostics regressions
- `PR-PERF-504` remains the cleanup PR that removes midpoint-only scaffolding
  after detached-daemon behavior is accepted as production truth
