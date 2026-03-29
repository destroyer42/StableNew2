# PR-RECOV-066: WebUI Recovery Hardening

## Summary

Harden the existing WebUI recovery path so hangs, readiness failures, HTTP 500
cascades, and partial image responses are treated as first-class runtime events
instead of narrow queue-only crash cases.

This PR is backend-only. It extends the existing recovery surfaces in:

- `src/api/client.py`
- `src/api/healthcheck.py`
- `src/api/webui_process_manager.py`
- `src/pipeline/executor.py`
- `src/queue/single_node_runner.py`

It does not introduce a new architecture path, GUI recovery flow, or a second
runner contract.

## Context

StableNew already has parts of a recovery story:

- HTTP retry/backoff in `SDWebUIClient._perform_request()`
- true-readiness gating in `Pipeline._ensure_webui_true_ready()`
- pre-stage health checks in `Pipeline._check_webui_health_before_stage()`
- queue-side restart/retry in `SingleNodeJobRunner._run_with_webui_retry()`
- process lifecycle restart in `WebUIProcessManager.restart_webui()`

The problem is that these pieces do not yet form one coherent policy.

### Current gaps

1. `Pipeline._check_webui_health_before_stage()` detects failures but does not
   attempt recovery.
2. `Pipeline._ensure_webui_true_ready()` fails hard on readiness timeout and
   never attempts restart/retry.
3. `WebUIProcessManager.restart_webui()` exposes `max_attempts`, `base_delay`,
   and `max_delay`, but currently does a single stop/start/readiness pass and
   ignores the retry parameters.
4. Queue retry only helps after a crash-classified exception escapes the stage
   call. Pre-stage readiness failures can still fail a job without a restart
   attempt.
5. `txt2img` already tolerates fewer returned images than requested, but that
   degraded result is not surfaced explicitly in the returned metadata or
   manifests.

### Evidence from repo review

- `src/pipeline/executor.py`:
  - `_ensure_webui_true_ready()` blocks generation but only raises on timeout
  - `_check_webui_health_before_stage()` logs and raises `PipelineStageError`
  - `_generate_images()` captures rich diagnostics but does not perform an
    executor-local restart/retry
- `src/api/webui_process_manager.py`:
  - `restart_webui()` has retry/backoff parameters that are not used
- `src/queue/single_node_runner.py`:
  - queue recovery is crash-driven and limited to exceptions that escape
- `src/pipeline/executor.py`:
  - `run_txt2img_stage()` already supports partial save success when some images
    are returned, but does not mark that as degraded execution

## Goals

1. Make stage execution resilient to WebUI readiness and mid-run health failures.
2. Make `restart_webui()` actually honor its retry contract.
3. Keep recovery classification consistent across executor and queue surfaces.
4. Surface partial image degradation explicitly in stage metadata/manifests.
5. Preserve the canonical runtime path:
   `NJR -> Queue/DIRECT -> PipelineRunner -> Pipeline executor -> History`

## Non-Goals

1. No GUI recovery redesign.
2. No new controller entrypoints.
3. No queue/history schema migration.
4. No new runner contract.
5. No aggressive "always retry everything" loop that can hide bad payloads.

## Allowed Files

- `src/api/healthcheck.py`
- `src/api/client.py`
- `src/api/types.py`
- `src/api/webui_process_manager.py`
- `src/pipeline/executor.py`
- `src/queue/single_node_runner.py`
- `tests/api/test_healthcheck_v2.py`
- `tests/api/test_webui_healthcheck.py`
- `tests/api/test_webui_process_manager.py`
- `tests/api/test_webui_process_manager_restart_ready.py`
- `tests/api/test_webui_retry_policy_v2.py`
- `tests/pipeline/test_executor_webui_true_ready_gate.py`
- `tests/pipeline/test_executor_webui_crash.py`
- `tests/pipeline/test_executor_generate_errors.py`
- `tests/pipeline/test_executor_n_iter_filenames.py`
- `tests/queue/test_single_node_runner_webui_retry.py`
- `docs/PR_MAR26/PR-RECOV-066-WebUI-Recovery-Hardening.md`

## Forbidden Files

- `src/gui/`
- `src/controller/`
- `src/pipeline/pipeline_runner.py`
- `src/pipeline/job_models_v2.py`
- `src/history/`
- `src/queue/job_model.py`
- canonical architecture docs outside this PR record

## Implementation

### Step 1: Add a single recovery classification contract

Use the existing diagnostics/error envelope path rather than inventing a second
error model.

Implementation requirements:

1. Add a small classification helper in `src/pipeline/executor.py` that
   distinguishes:
   - `true_ready_timeout`
   - `pre_stage_health_failed`
   - `request_connection_failure`
   - `request_http_500`
   - `request_timeout_escalated`
   - `partial_image_response`
2. Keep classification attached to existing `GenerateError.details` /
   error-envelope context.
3. Do not introduce a new persisted schema type just for recovery.

### Step 2: Make process restart honor retry parameters

In `src/api/webui_process_manager.py`:

1. Implement real retry/backoff behavior inside `restart_webui()` using the
   existing `max_attempts`, `base_delay`, and `max_delay` parameters.
2. Each restart attempt must:
   - stop current process
   - start new process
   - run true-readiness wait when `wait_ready=True`
3. Each failed attempt must log attempt index, reason, and readiness failure
   details.
4. Return `True` only when restart + readiness succeed.
5. Ensure client lifecycle cleanup still occurs per attempt.

This is a concrete correctness fix. The public signature already implies this
behavior.

### Step 3: Add executor-local recovery for readiness failures

In `src/pipeline/executor.py`:

1. `_ensure_webui_true_ready()` should attempt one bounded recovery restart when
   the true-readiness gate times out.
2. `_check_webui_health_before_stage(stage)` should attempt one bounded recovery
   restart when the pre-stage health probe fails.
3. After a successful restart, `_true_ready_gated` must be reset and the
   readiness gate re-run before generation resumes.
4. If recovery fails, raise `PipelineStageError` with recovery metadata in
   `details` and the attached error envelope context.

Boundaries:

- One executor-local recovery attempt per stage boundary.
- No infinite retry loops.
- No retry on payload validation errors caused by bad local input.

### Step 4: Add executor-local recovery for crash-classified request failures

In `src/pipeline/executor.py`:

1. When `_generate_images()` receives a failed `GenerateOutcome`, inspect the
   diagnostics context.
2. If the failure is crash-eligible or recovery-eligible, perform one bounded
   restart + retry at the executor layer before surfacing failure upward.
3. Recovery-eligible conditions include:
   - `crash_suspected == True`
   - `webui_unavailable == True`
   - HTTP 500 on crash-eligible generation stages
   - timeout escalation from queue-side-compatible classification
4. Preserve and enrich the attached error envelope with:
   - `recovery_attempted`
   - `recovery_reason`
   - `recovery_succeeded`
   - `recovery_attempt_count`

This must remain compatible with queue-side retry. The queue still owns
multi-attempt job-level recovery; the executor only gets one inline recovery
chance for the current stage call.

### Step 5: Keep queue-side crash retry aligned

In `src/queue/single_node_runner.py`:

1. Keep the current crash retry behavior, but align it with the executor-side
   recovery classification so both layers agree on timeout escalation and HTTP
   500 handling.
2. Do not remove queue retry.
3. Ensure retry attempt metadata and attached envelopes still reflect queue-level
   restarts distinctly from executor-local recovery.

The intended layering is:

- client: HTTP retry
- executor: single stage-local recovery
- queue: bounded job-level recovery

### Step 6: Surface partial image degradation explicitly

In `src/pipeline/executor.py`:

1. Preserve current behavior where returned images that save successfully are not
   discarded just because the count is lower than requested.
2. When `returned_images < expected_images` and `returned_images > 0`, mark the
   stage metadata as degraded:
   - `partial_success: true`
   - `expected_images`
   - `returned_images`
   - `saved_images`
   - `recovery_classification: partial_image_response`
3. Log a bounded warning when this occurs.
4. Persist that flag in the stage manifest/returned metadata without changing
   queue/history schemas.

This is intentionally conservative. It acknowledges partial success without
promoting a new artifact contract.

## Test Plan

### API / Process Manager

- `tests/api/test_webui_process_manager_restart_ready.py`
  - verify `restart_webui()` honors multi-attempt retry behavior
  - verify failed early attempts can succeed on a later attempt
  - verify retry parameters are actually exercised
- `tests/api/test_webui_process_manager.py`
  - verify `ensure_running()` behavior remains stable
- `tests/api/test_healthcheck_v2.py`
  - verify readiness timeout diagnostics remain bounded

### Executor

- `tests/pipeline/test_executor_webui_true_ready_gate.py`
  - gate timeout triggers one restart attempt, then succeeds or fails cleanly
- `tests/pipeline/test_executor_webui_crash.py`
  - crash-suspected failure triggers diagnostics plus executor-local recovery
- `tests/pipeline/test_executor_generate_errors.py`
  - payload validation remains non-recoverable
- `tests/pipeline/test_executor_n_iter_filenames.py`
  - partial image return path preserves saved outputs and marks degraded metadata

### Queue

- `tests/queue/test_single_node_runner_webui_retry.py`
  - queue retry still works
  - timeout escalation remains deterministic
  - queue retry metadata stays intact after executor-local recovery is added

## Verification

- `pytest tests/api/test_webui_process_manager_restart_ready.py tests/api/test_webui_process_manager.py tests/api/test_healthcheck_v2.py tests/api/test_webui_healthcheck.py tests/pipeline/test_executor_webui_true_ready_gate.py tests/pipeline/test_executor_webui_crash.py tests/pipeline/test_executor_generate_errors.py tests/pipeline/test_executor_n_iter_filenames.py tests/queue/test_single_node_runner_webui_retry.py -q`
- `pytest --collect-only -q`
- `python -m compileall src/api/healthcheck.py src/api/client.py src/api/types.py src/api/webui_process_manager.py src/pipeline/executor.py src/queue/single_node_runner.py`

## Acceptance Criteria

- `restart_webui()` uses its retry/backoff parameters for real.
- Pre-stage health failures attempt bounded recovery before failing the stage.
- True-readiness timeout attempts bounded recovery before failing the stage.
- Crash-eligible request failures get one executor-local restart+retry chance.
- Queue-level recovery still functions and remains bounded.
- Partial-image returns are surfaced explicitly in stage metadata/manifests.
- No GUI/controller files are touched.

## Risks

1. Double-recovery loops between executor and queue.
   Mitigation: executor gets one inline attempt; queue remains the outer bounded
   retry layer.
2. Hiding bad payload bugs behind restart attempts.
   Mitigation: payload validation and clearly local config errors remain
   non-recoverable.
3. Restart spam on persistent infrastructure failures.
   Mitigation: strict attempt caps and logged recovery classifications.

## Rollback

Revert the touched API/executor/queue files together. Do not partially keep
executor-local recovery without the restart contract fix in
`WebUIProcessManager.restart_webui()`.
