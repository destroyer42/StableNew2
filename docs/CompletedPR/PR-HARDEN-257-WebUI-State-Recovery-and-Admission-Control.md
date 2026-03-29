# PR-HARDEN-257 - WebUI State Recovery and Admission Control

Status: Completed 2026-03-21

## Summary

This PR converted the earlier pressure-warning pass into real runtime
stabilization. StableNew now checks runtime admission before heavy image stages,
can force guarded-profile WebUI recovery when runtime state is stale or
poisoned, and suppresses duplicate watchdog and diagnostics storms that were
previously amplifying failures.

## Delivered

- added runtime admission assessment and guarded recovery before heavy
  `txt2img`, `adetailer`, and `upscale` stages
- added explicit runtime failure-state tracking and progress snapshot helpers in
  the API client and healthcheck layers
- added managed WebUI restart support with profile override so recovery can
  relaunch under `sdxl_guarded`
- hardened diagnostics bundle creation and watchdog behavior so single-flight
  suppression is authoritative
- added process-risk snapshots for duplicate StableNew / WebUI / test-process
  conditions
- recorded runtime admission and pressure context in validation and diagnostics
  output

## Key Files

- `src/pipeline/executor.py`
- `src/api/client.py`
- `src/api/healthcheck.py`
- `src/api/webui_process_manager.py`
- `src/services/watchdog_system_v2.py`
- `src/utils/diagnostics_bundle_v2.py`
- `src/utils/process_inspector_v2.py`
- `tests/api/test_webui_runtime_recovery_v2.py`
- `tests/services/test_watchdog_singleflight_v2.py`
- `tests/pipeline/test_stage_admission_control_v2.py`

## Tests

Focused verification passed:

- `pytest tests/api/test_webui_runtime_recovery_v2.py tests/services/test_watchdog_singleflight_v2.py tests/pipeline/test_stage_admission_control_v2.py tests/api/test_webui_launch_profile_v2.py tests/services/test_watchdog_pressure_damping_v2.py tests/utils/test_diagnostics_bundle_pressure_context_v2.py tests/utils/test_memory_pressure_guard_v2.py tests/api/test_healthcheck_v2.py -q`
- result: `15 passed`

## Real Validation

Heavy real-world rerun against the same `AA LoRA Strength` workload class was
materially successful. Summary recorded in
`reports/pr257_validation_summary.json`.

Before (`PR-HARDEN-256` validation baseline):

- `10` jobs
- `3 / 10` complete `txt2img -> adetailer -> upscale` chains
- `7` failures
- average wall time: `323.08s`
- repeated timeouts and connection-refused failures
- `214` diagnostics bundles

After (`PR-HARDEN-257` validation rerun):

- `10` jobs
- `10 / 10` complete `txt2img -> adetailer -> upscale` chains
- `0` failures
- average wall time: `117.358s`
- `0` timeouts
- `0` connection-refused failures
- `0` diagnostics bundles

Observed peak pressure remained high, but the guarded recovery and admission
path kept the runtime stable enough to complete the workload:

- peak GPU utilization: `100%`
- peak dedicated VRAM: `11935 MiB`
- peak system RAM: `92.1%`
- launch profile used during validation: `sdxl_guarded`

## Documentation Updates

Bookkeeping closure recorded in:

- `docs/StableNew Roadmap v2.6.md`
- `docs/Research Reports/WebUI GPU Pressure and Stall Investigation 2026-03-21.md`
- `docs/Research Reports/deep-research-report-DEEP GPU memory and stall investigation - verdict.md`

## Follow-On Recommendation

`PR-HARDEN-257` is sufficient to unblock `PR-VIDEO-238`.

One non-blocking follow-on is still recommended:

- add workload-aware launch-policy selection so SDXL-heavy image workloads can
  automatically prefer `sdxl_guarded` without changing the global default for
  lighter jobs
