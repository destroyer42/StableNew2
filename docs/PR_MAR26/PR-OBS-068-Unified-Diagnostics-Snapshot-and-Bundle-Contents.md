# PR-OBS-068: Unified Diagnostics Snapshot and Bundle Contents

## Goal

Make diagnostics output more coherent across queue, runner, WebUI, and persistence by:
- giving `JobService` one richer runtime diagnostics snapshot shape
- making diagnostics bundles include that snapshot as a first-class artifact
- wiring WebUI tail and persisted queue state into the bundle path

## Scope

### Runtime
- `src/controller/job_service.py`
- `src/controller/app_controller.py`
- `src/utils/diagnostics_bundle_v2.py`
- `src/services/diagnostics_service_v2.py`

### Tests
- `tests/controller/test_job_service_unit.py`
- `tests/controller/test_app_controller_diagnostics.py`
- `tests/utils/test_diagnostics_bundle_v2.py`
- watchdog diagnostics regression coverage

## Implementation

1. `JobService.get_diagnostics_snapshot()` now returns:
   - per-job checkpoint state
   - control-action metadata
   - bounded result summaries
   - top-level queue state (`paused`, `auto_run_enabled`, `runner_running`, `current_job_id`, queued IDs)
2. `AppController._generate_diagnostics_bundle()` now passes:
   - current WebUI stdout/stderr tail when available
   - `include_process_state=True`
   - `include_queue_state=True`
3. `build_crash_bundle()` now writes:
   - `runtime/job_snapshot.json`
   - `runtime/webui_tail.json`
   - `runtime/queue_state.json` when the persisted queue snapshot exists and queue-state capture is requested
   - `metadata/process_inspector.txt` only when process-state capture is requested
4. `DiagnosticsServiceV2` now forwards the queue/process inclusion flags through both normal and fallback bundle paths.

## Why This PR

Before this PR:
- diagnostics bundles had job snapshot data only embedded inside `metadata/info.json`
- queue/process inclusion flags existed but were effectively ignored
- manual/watchdog bundles did not include WebUI tail even when the process manager had it
- queue/running-job state and checkpoint state were harder to inspect quickly during failures

After this PR:
- operators get one consistent runtime snapshot shape
- bundles contain concrete runtime artifacts instead of only a summary blob
- queue state, WebUI tail, and checkpoint progress are easier to inspect during recovery triage

## Verification

- `pytest tests/controller/test_job_service_unit.py tests/controller/test_app_controller_diagnostics.py tests/utils/test_diagnostics_bundle_v2.py tests/system/test_watchdog_ui_stall.py tests/services/test_watchdog_ui_stall_context.py -q`
- `pytest --collect-only -q`
- `python -m compileall src/controller/job_service.py src/controller/app_controller.py src/utils/diagnostics_bundle_v2.py src/services/diagnostics_service_v2.py tests/controller/test_job_service_unit.py tests/controller/test_app_controller_diagnostics.py tests/utils/test_diagnostics_bundle_v2.py`

## Notes

- This PR improves observability artifacts and snapshot coherence; it does not introduce a new event bus or change runner architecture.
- The next planned PR in sequence remains `PR-IO-069`.
