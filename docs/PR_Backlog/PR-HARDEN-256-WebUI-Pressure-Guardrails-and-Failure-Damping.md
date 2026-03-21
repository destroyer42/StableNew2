# PR-HARDEN-256 - WebUI Pressure Guardrails and Failure Damping

Status: Specification
Priority: CRITICAL
Effort: LARGE
Phase: Runtime Stability Hardening
Date: 2026-03-21

## 2. Context & Motivation

### Current Repo Truth

StableNew is currently seeing recurring image-pipeline failures under heavy SDXL
workloads. Recent evidence from live manifests, WebUI stdout, diagnostics
bundles, process inspection, and GPU telemetry shows a compound failure mode:

- large SDXL generation and detail pipelines push a 12 GB GPU near full VRAM
  saturation
- WebUI can become extremely slow, unresponsive, or unavailable under that
  pressure
- StableNew then amplifies the unhealthy state through repeated readiness
  polling, repeated watchdog bundles, and repeated failure churn
- diagnostics currently omit too much process/WebUI state to distinguish real
  pressure events from shutdown/restart thrash
- live model drift is still observable in WebUI stdout even when recent
  manifests appear pinned correctly

### Specific Problem

The current runtime stack has weak guardrails for GPU pressure and weak damping
for post-failure behavior. That combination produces:

- hard-to-diagnose timeouts
- repeated WebUI restarts or refusal cycles
- operator-visible heartbeat-stall spam
- fragile runtime validation for new work

### Why This PR Exists Now

This is an interstitial hardening PR that should land before more runtime
feature work. Continuing directly into more video-runtime rollout would be the
wrong order while the image/runtime base remains unstable under pressure.

### References

- `docs/ARCHITECTURE_v2.6.md`
- `docs/StableNew Roadmap v2.6.md`
- `docs/WebUI GPU Pressure and Stall Investigation 2026-03-21.md`
- `docs/WebUI Restart and Lost Connection Investigation 2026-03-20.md`
- `docs/PR_Backlog/PR-HARDEN-230-ADetailer-Payload-Checkpoint-Pinning-and-Detector-Model-Key-Cleanup.md`
- `docs/PR_Backlog/PR-HARDEN-231-Output-Root-Normalization-and-Route-Classification-Audit.md`

## 3. Goals & Non-Goals

### Goals

1. Add StableNew-owned GPU-pressure risk classification before `txt2img`,
   `adetailer`, and `upscale` execution.
2. Surface explicit operator warnings when stage dimensions and settings are
   likely unsafe for the active hardware/runtime profile.
3. Add failure damping so repeated WebUI readiness failures, watchdog triggers,
   and diagnostics bundles do not flood the system.
4. Introduce a managed WebUI launch-profile policy with an SDXL-guarded mode
   that can use lower-memory launch flags.
5. Improve diagnostics bundles for stall/pressure incidents so they include the
   process/WebUI state needed to debug real failures.
6. Add explicit warning/reporting when live WebUI model state diverges from the
   requested stage model intent.

### Non-Goals

1. Do not change NJR, queue ownership, or the canonical outer execution path.
2. Do not redesign the whole GUI.
3. Do not add GPU vendor-specific direct memory control beyond safe telemetry and
   warnings.
4. Do not attempt to fully solve all WebUI/plugin global-state bugs in this PR.
5. Do not continue video-backend rollout work in the same PR.

## 4. Guardrails

1. The canonical execution path remains:
   `PromptPack -> Builder -> NJR -> Queue -> Runner -> Executor -> Artifacts`.
2. No new job model or alternate execution path may be introduced.
3. Any new runtime policy must remain StableNew-owned and visible through logs,
   diagnostics, and config, not hidden ambient behavior.
4. Launch-profile changes must be additive and explicit, not silent hard-coded
   overrides with no operator visibility.
5. Watchdog hardening must reduce noise without suppressing first-occurrence
   failure evidence.

## 5. Allowed Files

### Files to Create

- `tests/utils/test_memory_pressure_guard_v2.py`
- `tests/services/test_watchdog_pressure_damping_v2.py`
- `tests/api/test_webui_launch_profile_v2.py`
- `tests/utils/test_diagnostics_bundle_pressure_context_v2.py`

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
- `src/utils/logger.py`
- focused tests under:
  - `tests/api/`
  - `tests/pipeline/`
  - `tests/services/`
  - `tests/utils/`
- `docs/StableNew Roadmap v2.6.md`
- `docs/DOCS_INDEX_v2.6.md`
- `docs/CompletedPR/PR-HARDEN-256-WebUI-Pressure-Guardrails-and-Failure-Damping.md`

### Forbidden Files

- `src/gui/**` except if a test import requires a minimal fixture update
- `src/controller/**`
- `src/video/**`
- `docs/ARCHITECTURE_v2.6.md`
- archived or compat-only runtime paths

## 6. Implementation Plan

### Step 1: Add pressure classification and admission logic

Add a StableNew-owned risk helper for image pipeline stages.

Required behavior:

- estimate per-stage pixel pressure using current stage dimensions, upscale
  target size, enabled passes, and batch settings
- classify as `normal`, `high_pressure`, or `unsafe`
- include conservative thresholds for SDXL-class image work
- use the helper before `txt2img`, `adetailer`, and `upscale`
- emit explicit warnings into logs and stage metadata

Files:

- modify `src/pipeline/executor.py`
- modify `src/pipeline/pipeline_runner.py`
- create `tests/utils/test_memory_pressure_guard_v2.py`
- update focused executor/pipeline tests

### Step 2: Add managed WebUI launch profiles

Introduce an explicit StableNew launch-profile layer rather than a single fixed
command.

Required behavior:

- support at least:
  - `standard`
  - `sdxl_guarded`
  - `low_memory`
- keep `standard` close to current `--api --xformers`
- allow `sdxl_guarded` to use local WebUI-supported low-memory flags such as
  `--medvram-sdxl`
- record the resolved launch profile in logs and diagnostics
- keep the chosen launch profile deterministic and inspectable

Files:

- modify `src/config/app_config.py`
- modify `src/api/webui_process_manager.py`
- create `tests/api/test_webui_launch_profile_v2.py`

### Step 3: Add failure damping and circuit-breaker behavior

Reduce repeated unhealthy-state amplification after WebUI destabilizes.

Required behavior:

- introduce a restart/readiness backoff after repeated consecutive failures
- suppress repeated identical readiness storms more aggressively
- make watchdog cooldowns materially longer for `ui_heartbeat_stall`
- avoid firing `ui_heartbeat_stall` bundles while shutdown is already in
  progress
- avoid repeated bundle generation when the main thread is already dead or the
  app is tearing down

Files:

- modify `src/api/client.py`
- modify `src/api/healthcheck.py`
- modify `src/services/watchdog_system_v2.py`
- modify `src/utils/diagnostics_bundle_v2.py`
- create `tests/services/test_watchdog_pressure_damping_v2.py`
- update `tests/test_api_client.py`

### Step 4: Improve diagnostics and runtime observability

Make pressure/stall bundles useful for this class of incident.

Required behavior:

- include process state by default for pressure/stall reasons
- include recent WebUI stdout/stderr tail by default for pressure/stall reasons
- include launch profile and tracked WebUI PID lineage
- include whether shutdown was already in progress when the bundle was triggered
- if available, include a best-effort GPU snapshot using existing local tooling
  without making external tools mandatory

Files:

- modify `src/utils/diagnostics_bundle_v2.py`
- modify `src/utils/process_inspector_v2.py`
- create `tests/utils/test_diagnostics_bundle_pressure_context_v2.py`

### Step 5: Add model-drift warning guardrails

Do not attempt the full final fix here, but do make drift visible and
actionable.

Required behavior:

- compare requested stage model intent with live WebUI current model at stage
  entry and stage exit where safe
- emit a structured warning when drift is observed
- attach the drift warning into manifest/diagnostics metadata if it occurs
- do not silently overwrite requested provenance with ambient live state

Files:

- modify `src/pipeline/executor.py`
- update focused executor manifest tests

### Step 6: Close the docs and backlog truth

Record the hardening PR in the active plan and document the investigation.

Files:

- modify `docs/StableNew Roadmap v2.6.md`
- modify `docs/DOCS_INDEX_v2.6.md`
- create `docs/CompletedPR/PR-HARDEN-256-WebUI-Pressure-Guardrails-and-Failure-Damping.md`

## 7. Testing Plan

### Unit Tests

- `tests/utils/test_memory_pressure_guard_v2.py`
- `tests/api/test_webui_launch_profile_v2.py`
- `tests/services/test_watchdog_pressure_damping_v2.py`
- `tests/utils/test_diagnostics_bundle_pressure_context_v2.py`

### Integration Tests

- focused executor and pipeline tests around:
  - pressure classification
  - pre-stage warning behavior
  - model-drift warning emission
  - readiness/retry damping

### Journey or Smoke Coverage

- one local image journey under large SDXL dimensions with guarded profile
- one forced WebUI-down / readiness-failure path to verify damping and bundle
  behavior

### Manual Verification

1. Run a large SDXL image pipeline and confirm pressure warnings are emitted
   before risky stages.
2. Confirm repeated WebUI outage does not spam dozens of diagnostics bundles.
3. Confirm diagnostics bundles for stall reasons now include process/WebUI state.
4. Confirm launch profile is visible in logs and diagnostics.
5. Confirm unexpected live model drift emits a structured warning.

Suggested pytest commands:

- `pytest tests/utils/test_memory_pressure_guard_v2.py tests/services/test_watchdog_pressure_damping_v2.py tests/api/test_webui_launch_profile_v2.py tests/utils/test_diagnostics_bundle_pressure_context_v2.py tests/test_api_client.py tests/pipeline/test_executor_adetailer.py tests/pipeline/test_executor_refinement_manifest.py tests/pipeline/test_pipeline_runner.py -q`
- `pytest --collect-only -q`

## 8. Verification Criteria

### Success Criteria

1. StableNew warns before obviously unsafe high-pressure stage combinations.
2. Repeated WebUI failure does not flood logs, watchdog bundles, or readiness
   retries at the current rate.
3. Pressure/stall bundles now contain usable process and WebUI state.
4. Launch policy is explicit, deterministic, and inspectable.
5. Live model-drift events are surfaced as warnings instead of staying silent.

### Failure Criteria

1. The PR only increases timeouts and does not change pressure handling or
   failure damping.
2. Watchdog and diagnostics spam remain effectively unchanged.
3. Launch policy changes are hidden and not visible in logs or diagnostics.
4. Pressure warnings exist but do not trigger on the current failing class of
   workload.
5. Model drift remains completely silent.

## 9. Risk Assessment

### Low-Risk Areas

- diagnostics payload expansion
- explicit log and warning additions

### Medium-Risk Areas with Mitigation

- low-memory launch profile may reduce throughput
  - Mitigation: keep profile explicit and policy-driven, not mandatory

### High-Risk Areas with Mitigation

- over-aggressive damping could hide real failures
  - Mitigation: preserve first occurrence, preserve structured errors, damp only
    repetition
- over-conservative pressure heuristics could block viable jobs
  - Mitigation: warn first, reserve hard refusal only for clearly unsafe cases

### Rollback Plan

Rollback the launch-profile and damping changes while retaining the added
diagnostic/reporting helpers if needed. Do not leave partial duplicate runtime
policies active.

## 10. Tech Debt Analysis

### Debt Removed

- lack of GPU-pressure-aware admission warnings
- runaway watchdog/diagnostics spam during prolonged WebUI failure
- weak diagnostics for pressure/stall incidents

### Debt Intentionally Deferred

- full root-cause closure of all live model-switch drift
  - Owner: follow-on hardening PR after `PR-HARDEN-256`
- broader controller/UI surfacing of runtime pressure state
  - Owner: future GUI/runtime observability follow-on

## 11. Documentation Updates

- `docs/StableNew Roadmap v2.6.md`
- `docs/DOCS_INDEX_v2.6.md`
- `docs/WebUI GPU Pressure and Stall Investigation 2026-03-21.md`
- `docs/CompletedPR/PR-HARDEN-256-WebUI-Pressure-Guardrails-and-Failure-Damping.md`

## 12. Dependencies

### Internal Module Dependencies

- current WebUI client
- current process manager
- current executor/pipeline runner
- current diagnostics/watchdog surfaces

### External Tools or Runtimes

- local Automatic1111/WebUI install
- optional `nvidia-smi` availability for richer diagnostics

## 13. Approval & Execution

Planner: Codex  
Executor: Codex  
Reviewer: Human  
Approval Status: Pending

## 14. Next Steps

1. Implement `PR-HARDEN-256` before continuing runtime-heavy video rollout.
2. Resume with `PR-VIDEO-238-SVD-Native-Secondary-Motion-Postprocess-Integration`
   after the hardening pass is complete.
