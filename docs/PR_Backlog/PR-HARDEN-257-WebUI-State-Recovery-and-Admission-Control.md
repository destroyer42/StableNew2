# PR-HARDEN-257 - WebUI State Recovery and Admission Control

Status: Specification
Priority: CRITICAL
Effort: LARGE
Phase: Runtime Stability Hardening
Date: 2026-03-21

## 1. Why This PR Exists

`PR-HARDEN-256` improved observability and added first-pass pressure guardrails,
but real validation on the live `AA LoRA Strength` workload still failed too
often to call the runtime stable.

Observed post-`256` validation truth:

- 10 sequential image jobs produced only 3 complete `txt2img -> adetailer ->
  upscale` chains
- GPU remained pinned near saturation at `11956 MiB / 12282 MiB` and `100%`
  utilization
- system RAM peaked at `98.6%`
- the workload still produced repeated `WebUI unavailable`, connection-reset,
  and connection-refused failures
- `ui_heartbeat_stall` diagnostics continued to flood the system
- large stale Python/WebUI resident processes were still present
- the guarded launch profile was implemented in code but was not enforced for
  the already-running WebUI instance

Conclusion:

StableNew still admits work into a poisoned runtime state. The next fix must be
state recovery and admission control, not just better warnings.

## 2. Goals

1. Detect stale or poisoned WebUI runtime state before a heavy image job starts.
2. Refuse or defer unsafe stage execution instead of only logging warnings.
3. Force a clean guarded-profile restart path when runtime state is unhealthy.
4. Guarantee watchdog and diagnostics single-flight behavior per app process.
5. Detect and surface orphan or duplicate StableNew/WebUI process conditions.
6. Record explicit recovery reasons and admission decisions in logs and
   manifests.

## 3. Non-Goals

1. Do not redesign the GUI in this PR.
2. Do not continue secondary-motion runtime rollout in this PR.
3. Do not solve every Automatic1111 plugin-global-state issue here.
4. Do not introduce a second execution path outside the canonical NJR pipeline.

## 4. Required Findings Incorporated

### Finding A: Pressure warnings alone are insufficient

`PR-HARDEN-256` classified pressure correctly, but the executor still attempted
`high_pressure` and effectively `unsafe` work. This PR must add hard admission
gates and downgrade/defer behavior.

### Finding B: Existing WebUI state matters

The live run reused a WebUI instance that already showed stale progress and near
full VRAM. This PR must validate runtime state before admitting heavy jobs and
must support a forced clean restart into the managed guarded profile.

### Finding C: Diagnostics/watchdog spam is still active

Recent bundles show repeated `ui_heartbeat_stall` saves inside the same minute
despite the intended cooldowns. This PR must make single-flight and cooldown
behavior authoritative at the active watchdog/bundle path.

### Finding D: Process hygiene is not trustworthy enough

Recent process inspection found multiple long-lived Python processes with
multi-GB working sets and at least one active WebUI lineage. This PR must make
duplicate-process state visible and actionable.

## 5. Allowed Files

### Files to Modify

- `src/api/client.py`
- `src/api/healthcheck.py`
- `src/api/webui_process_manager.py`
- `src/config/app_config.py`
- `src/pipeline/executor.py`
- `src/pipeline/pipeline_runner.py`
- `src/services/watchdog_system_v2.py`
- `src/utils/diagnostics_bundle_v2.py`
- `src/utils/process_inspector_v2.py`
- focused tests under:
  - `tests/api/`
  - `tests/pipeline/`
  - `tests/services/`
  - `tests/utils/`
- `docs/StableNew Roadmap v2.6.md`
- `docs/DOCS_INDEX_v2.6.md`

### Files to Create

- `tests/api/test_webui_runtime_recovery_v2.py`
- `tests/services/test_watchdog_singleflight_v2.py`
- `tests/pipeline/test_stage_admission_control_v2.py`

### Forbidden Files

- `src/gui/**`
- `src/controller/**`
- `src/video/**`
- `docs/ARCHITECTURE_v2.6.md`
- archive-only runtime paths

## 6. Implementation Plan

### Step 1: Add runtime-state admission checks

Before heavy image execution begins, assess whether the active WebUI/runtime
state is safe enough to continue.

Required signals:

- current WebUI availability
- current progress endpoint freshness
- current launch profile
- current GPU snapshot
- current duplicate-process / orphan-process warning state
- current recent hard-failure count

Required behavior:

- classify runtime as `healthy`, `degraded`, or `poisoned`
- `poisoned` state must prevent admitting new heavy jobs
- record the admission decision in logs and run metadata

### Step 2: Add guarded clean-restart recovery

When runtime state is `poisoned`, StableNew must be able to:

- stop the tracked WebUI process cleanly
- clear readiness and resource-endpoint failure state
- relaunch using the managed `sdxl_guarded` profile
- wait for a healthy readiness confirmation before retrying

If restart fails:

- fail fast with an explicit recovery error instead of repeated silent churn

### Step 3: Add stage-level refusal for unsafe pressure states

Current `high_pressure` / `unsafe` warnings are insufficient.

Required behavior:

- executor must refuse clearly unsafe `upscale` attempts
- executor must be able to refuse `adetailer` when combined pressure plus live
  runtime state is unsafe
- refusals must be recorded as explicit runtime warnings / operator-visible
  errors, not generic WebUI timeouts

### Step 4: Make watchdog and diagnostics single-flight authoritative

Required behavior:

- only one active watchdog instance may trigger diagnostics for a given app
  process
- identical `ui_heartbeat_stall` bundle creation must be single-flight and
  cooldown-protected across all active callers
- duplicate "Crash bundle saved ..." spam for the same timestamp/reason must be
  eliminated

### Step 5: Surface duplicate-process risk

Required behavior:

- diagnostics/process inspection should flag multiple likely StableNew or stale
  pytest Python processes with large working sets
- startup/runtime logs should emit an operator warning when duplicate
  StableNew-like processes are present
- metadata should capture that duplicate-process risk was present during the run

## 7. Tests

Required focused coverage:

- runtime recovery enters guarded restart path on poisoned state
- readiness/resource cooldowns are cleared after successful guarded restart
- unsafe stage admission is refused deterministically
- watchdog single-flight prevents repeated identical bundle saves
- duplicate-process detection flags suspicious runtime conditions without false
  positives on normal helper processes

Suggested verification commands:

- `pytest tests/api/test_healthcheck_v2.py tests/api/test_webui_runtime_recovery_v2.py tests/services/test_watchdog_singleflight_v2.py tests/pipeline/test_stage_admission_control_v2.py tests/utils/test_diagnostics_bundle_pressure_context_v2.py -q`
- `python -m compileall src/api src/pipeline src/services src/utils`

## 8. Success Criteria

1. Heavy runs do not start against a poisoned WebUI state.
2. Guarded restart can be triggered and verified before retrying heavy work.
3. Unsafe `upscale` / `adetailer` work is refused early instead of timing out
   deep in WebUI.
4. `ui_heartbeat_stall` bundle spam is materially reduced.
5. Duplicate-process / stale-process conditions are visible in operator logs and
   diagnostics.

## 9. Follow-On Validation Requirement

This PR must be validated with a real repeated SDXL image run, not just focused
tests.

Minimum validation:

- 10 sequential image jobs
- same workload class as the failing `AA LoRA Strength` run
- capture wall time, per-stage duration, success rate, timeout count,
  connection-refused count, diagnostics bundle count, peak VRAM, and peak system
  RAM

`PR-VIDEO-238` should remain blocked until that validation is materially better
than the post-`256` baseline.
