# PR-HARDEN-256 - WebUI Pressure Guardrails and Failure Damping

Status: Completed 2026-03-21

## Summary

This PR added the first StableNew-owned pressure and damping layer around the
WebUI-backed image path. StableNew now classifies heavy image-stage pressure
before execution, exposes managed guarded launch profiles, captures richer
pressure/stall diagnostics, and makes live model drift visible enough to drive
follow-on runtime recovery work.

## Delivered

- added pre-stage pressure assessment, warning, and runtime-admission helpers
  in `src/pipeline/executor.py`, including `normal`, `high_pressure`, and
  `unsafe` classification for heavy `txt2img`, `adetailer`, and `upscale`
  work
- added managed WebUI launch-profile resolution in `src/config/app_config.py`
  and `src/api/webui_process_manager.py`, including `standard`,
  `sdxl_guarded`, `sdxl_adetailer_guarded`, `sdxl_adetailer_no_half`, and
  `low_memory`
- added readiness-failure damping and cooldown behavior in
  `src/api/healthcheck.py`, `src/api/client.py`, and
  `src/services/watchdog_system_v2.py`
- extended pressure and stall diagnostics with process-state capture, WebUI
  stdout/stderr tail capture, and launch-profile visibility in
  `src/utils/diagnostics_bundle_v2.py`,
  `src/utils/process_inspector_v2.py`, and
  `src/api/webui_process_manager.py`
- added live model-drift warning capture and manifest/runtime warning helpers
  in `src/pipeline/executor.py`
- added focused validation coverage for pressure classification, launch-profile
  policy, watchdog damping, and diagnostics bundle enrichment

## Key Files

- `src/pipeline/executor.py`
- `src/config/app_config.py`
- `src/api/healthcheck.py`
- `src/api/client.py`
- `src/api/webui_process_manager.py`
- `src/services/watchdog_system_v2.py`
- `src/utils/diagnostics_bundle_v2.py`
- `src/utils/process_inspector_v2.py`
- `tests/utils/test_memory_pressure_guard_v2.py`
- `tests/api/test_webui_launch_profile_v2.py`
- `tests/services/test_watchdog_pressure_damping_v2.py`
- `tests/utils/test_diagnostics_bundle_pressure_context_v2.py`

## Tests

Focused verification passed:

- `c:/Users/rob/projects/StableNew/.venv/Scripts/python.exe -m pytest tests/utils/test_memory_pressure_guard_v2.py tests/api/test_webui_launch_profile_v2.py tests/services/test_watchdog_pressure_damping_v2.py tests/utils/test_diagnostics_bundle_pressure_context_v2.py -q`
- result: `13 passed in 0.51s`

## Real Validation

Documented live validation after implementation showed that `PR-HARDEN-256`
improved observability and added first-pass damping, but did not materially
stabilize the heavy `AA LoRA Strength` workload class on its own.

Recorded validation summary:

- `10` sequential image jobs
- `3 / 10` complete `txt2img -> adetailer -> upscale` chains
- `7` failed jobs
- average wall time: `323.08s`
- peak GPU utilization: `100%`
- peak dedicated VRAM: `11956 MiB / 12282 MiB`
- peak system RAM: `98.6%`
- diagnostics bundles created: `214`

This outcome confirmed that pressure classification and damping were necessary
but not sufficient. The required admission-control and guarded-recovery follow-on
was then delivered by `PR-HARDEN-257`.

## Documentation Updates

Bookkeeping closure recorded in:

- `docs/StableNew Roadmap v2.6.md`
- `docs/DOCS_INDEX_v2.6.md`

Supporting investigation and verdict references remain in:

- `docs/Research Reports/WebUI GPU Pressure and Stall Investigation 2026-03-21.md`
- `docs/Research Reports/deep-research-report-DEEP GPU memory and stall investigation - verdict.md`

## Follow-On Recommendation

`PR-HARDEN-256` should be treated as the observability and first-damping
foundation only.

Required follow-on delivered:

- `PR-HARDEN-257` for runtime-state recovery and admission control

Non-blocking follow-on delivered after that:

- `PR-HARDEN-258` for workload-aware guarded launch-profile selection
