# PR-COMFY-209 - Managed Comfy Runtime and Dependency Probes

Status: Completed 2026-03-19

## Purpose

Add a StableNew-managed local Comfy runtime parallel to WebUI so later workflow
execution can be supervised, health-checked, and dependency-validated without
leaking Comfy details outside `src/video/`.

## What Changed

### Managed Comfy runtime

Added:

- `src/video/comfy_process_manager.py`

This introduces:

- `ComfyProcessConfig`
- `ComfyProcessManager`
- `ComfyStartupError`
- `build_default_comfy_process_config(...)`

Behavior now covered:

- deterministic `start()`
- deterministic `stop()`
- `ensure_running()`
- `restart()`
- stdout/stderr tail capture
- explicit managed runtime defaults from engine settings

### Comfy health and client layer

Added:

- `src/video/comfy_api_client.py`
- `src/video/comfy_healthcheck.py`

This adds:

- `/system_stats` and `/object_info` probing
- `wait_for_comfy_ready(...)`
- `validate_comfy_health(...)`
- lightweight API access for system stats, object info, queue state, and prompt
  submission

### Workflow dependency probing

Added:

- `src/video/comfy_dependency_probe.py`

This gives StableNew a pre-execution dependency check against registered
workflow metadata so missing nodes/models can be detected before the actual
workflow execution PR lands.

### Settings and startup wiring

Updated:

- `src/utils/config.py`
- `src/main.py`
- `src/gui/main_window_v2.py`
- `src/video/__init__.py`

New default engine settings now include:

- `comfy_base_url`
- `comfy_workdir`
- `comfy_command`
- `comfy_autostart_enabled`
- `comfy_health_*`

`main.py` now has:

- `bootstrap_comfy(...)`
- `_load_comfy_config()`
- `_async_bootstrap_comfy(...)`
- `_update_window_comfy_manager(...)`

`MainWindowV2.cleanup()` now stops a managed Comfy runtime if one was attached
to the window during startup.

## Skipped Test Note

The one global skipped test is still:

- `tests/video/test_svd_postprocess_worker.py`

Reason:

- it uses `pytest.importorskip("cv2")`
- this environment does not have OpenCV installed

This is not a regression from the Comfy work. It should stay skipped unless
OpenCV becomes a required test/developer dependency or that test is rewritten to
mock `cv2`.

## Tests

Added:

- `tests/video/test_comfy_api_client.py`
- `tests/video/test_comfy_healthcheck.py`
- `tests/video/test_comfy_dependency_probe.py`
- `tests/video/test_comfy_process_manager.py`
- `tests/app/test_bootstrap_comfy_autostart.py`

Verification:

- `pytest tests/video/test_comfy_api_client.py tests/video/test_comfy_healthcheck.py tests/video/test_comfy_dependency_probe.py tests/video/test_comfy_process_manager.py tests/app/test_bootstrap_comfy_autostart.py -q`
- `pytest tests/app/test_bootstrap_webui_autostart.py tests/gui_v2/test_engine_settings_dialog_v2.py tests/pipeline/test_video.py -q`
- `pytest --collect-only -q -rs` -> `2370 collected / 1 skipped`
- `python -m compileall src/video/comfy_api_client.py src/video/comfy_healthcheck.py src/video/comfy_dependency_probe.py src/video/comfy_process_manager.py src/utils/config.py src/main.py src/gui/main_window_v2.py tests/video/test_comfy_api_client.py tests/video/test_comfy_healthcheck.py tests/video/test_comfy_dependency_probe.py tests/video/test_comfy_process_manager.py tests/app/test_bootstrap_comfy_autostart.py`

## Architectural Result

StableNew now has a managed local Comfy runtime substrate with explicit health
and dependency checking, while preserving the v2.6 invariants:

- NJR remains the only outer job contract
- queue/runner/history/artifacts remain StableNew-owned
- no Comfy imports leak outside `src/video/` and minimal startup wiring
- workflow execution itself is still deferred to the pinned LTX PR

## Deferred To Next PR

Owned by `PR-COMFY-210`:

- actual execution of the pinned `ltx_multiframe_anchor_v1` workflow
- replayable workflow execution metadata from real Comfy runs
- canonical artifact/history population from a real Comfy-backed video job

Next planned PR: `PR-COMFY-210`
