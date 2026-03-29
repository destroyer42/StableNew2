# PR-HARDEN-281 - ADetailer Stability Closure and Request-Local Pinning Rollback

Status: Specification
Priority: HIGH
Effort: MEDIUM
Phase: Runtime Stability Hardening
Date: 2026-03-26

## Context & Motivation

### Current Repo Truth

Recent branch work improved ADetailer observability and surfaced a real runtime
regression: under A1111, the newer request-local `sd_model` / `sd_vae` pinning
path for ADetailer triggered repeated `NansException` failures across multiple
SDXL checkpoints. Live validation showed the older global-switch ADetailer path
remained materially more stable.

The current working tree already contains a mitigation:

- ADetailer defaults to the global model/VAE switch path
- request-local ADetailer pinning remains opt-in
- ambient `/options` model mismatch is downgraded when request-local override is
  intentionally active

### Specific Problem

The branch needs a clean, reviewed closure of the ADetailer regression rather
than leaving the fix as ad hoc local debugging residue.

### Why This PR Exists Now

`D-016` identified this as the highest-value runtime fix after test-trust
recovery. It directly impacts production use of ADetailer on the active branch.

### Reference

- `docs/ARCHITECTURE_v2.6.md`
- `docs/GOVERNANCE_v2.6.md`
- `docs/Research Reports/D-016-Branch-Review-Since-2026-03-22-2205.md`
- `docs/CompletedPR/PR-HARDEN-230-ADetailer-Payload-Checkpoint-Pinning-and-Detector-Model-Key-Cleanup.md`

## Goals & Non-Goals

### Goals

1. Make the global model/VAE switch path the default ADetailer execution path.
2. Keep request-local ADetailer model/VAE pinning available only as an explicit
   opt-in for future validation.
3. Preserve the improved ADetailer diagnostics added during debugging.
4. Preserve the non-restart behavior for deterministic inference errors such as
   `NansException`.
5. Reduce misleading `stage_model_drift` noise for stages intentionally using
   request-local overrides.

### Non-Goals

1. Do not redesign ADetailer as a separate pipeline architecture.
2. Do not remove request-local pinning for txt2img or upscale.
3. Do not broaden this PR into general WebUI launch-profile experimentation.
4. Do not change builder/NJR schema for this fix unless absolutely required.

## Guardrails

1. Preserve the canonical NJR -> Queue -> Runner execution path.
2. No alternate ADetailer stage architecture may be introduced.
3. Queue and runner contracts must remain intact.
4. GUI changes are out of scope unless a tiny diagnostic string or config flag
   label change is required, which is not currently expected.
5. The fix must remain explicit about whether ADetailer is using global-switch
   or request-local model context.

## Allowed Files

### Files to Create

| File | Purpose |
| ------ | ------- |
| None expected | |

### Files to Modify

| File | Reason |
| ------ | ------ |
| `src/pipeline/executor.py` | Finalize ADetailer default model/VAE context behavior and drift-warning semantics |
| `src/config/app_config.py` | Finalize env flag semantics for request-local ADetailer pinning |
| `src/api/client.py` | Only if a tiny comment or helper adjustment is required for model-context clarity |
| `tests/pipeline/test_executor_adetailer.py` | Assert default-global behavior and request-local opt-in behavior |
| `tests/api/test_webui_launch_profile_v2.py` | Assert env-flag behavior if needed |
| `tests/pipeline/test_stage_admission_control_v2.py` | Keep runtime-admission expectations aligned if touched |
| `tests/pipeline/test_executor_generate_errors.py` | Preserve no-restart behavior for deterministic inference errors |

### Forbidden Files

| File/Directory | Reason |
| ---------------- | ------ |
| `src/pipeline/pipeline_runner.py` | No runner architecture change required |
| `src/controller/**` | No controller work |
| `src/gui/**` | No GUI work |
| `docs/ARCHITECTURE_v2.6.md` | No architecture change |
| `docs/StableNew Roadmap v2.6.md` | Separate docs PR handles roadmap harmonization |

## Implementation Plan

### Step 1: Finalize default ADetailer model/VAE context behavior

Ensure ADetailer uses the global-switch model/VAE path by default and only
enters request-local pinning when the explicit opt-in flag is set.

Required details:

- keep the request-local path available for future debugging
- keep diagnostics explicit about which path was used

Files:

- modify `src/pipeline/executor.py`
- modify `src/config/app_config.py`

Tests:

- update `tests/pipeline/test_executor_adetailer.py`
- update `tests/api/test_webui_launch_profile_v2.py` if env behavior is covered there

### Step 2: Keep deterministic inference failures from causing recovery churn

Preserve the existing behavior that treats structured A1111 application errors
such as `NansException` as non-recoverable stage failures rather than restart
triggers.

Files:

- modify `src/pipeline/executor.py` only if cleanup is needed
- modify `tests/pipeline/test_executor_generate_errors.py` if needed

Tests:

- rerun `tests/pipeline/test_executor_generate_errors.py`

### Step 3: Downgrade misleading ambient-model noise under request-local mode

Keep `_check_model_drift()` from producing a hard warning when the mismatch is
just WebUI ambient `/options` state under an intentional request-local stage.

Files:

- modify `src/pipeline/executor.py`
- modify `src/api/client.py` only if required for a tiny helper/comment cleanup

Tests:

- update `tests/pipeline/test_executor_adetailer.py`
- update any model-context logging tests if they exist

### Step 4: Verify against the known failing path

Run focused test coverage and, if practical, one manual ADetailer run on the
known failing SDXL path to confirm the default-global behavior is now stable.

Files:

- no additional files expected beyond tests

Tests:

- focused pytest commands below

## Testing Plan

### Unit Tests

- `pytest tests/pipeline/test_executor_adetailer.py -q`
- `pytest tests/pipeline/test_executor_generate_errors.py -q`
- `pytest tests/api/test_webui_launch_profile_v2.py -q`

### Integration Tests

- `pytest tests/pipeline/test_stage_admission_control_v2.py -q`

### Journey or Smoke Coverage

- optional manual rerun of a previously failing ADetailer SDXL case on the live
  app

### Manual Verification

1. Confirm default ADetailer runs log the global-switch path.
2. Confirm `STABLENEW_ADETAILER_REQUEST_LOCAL_PINNING=1` restores the
   request-local path for experimentation.
3. Confirm a deterministic `NansException` fails the stage without restarting
   WebUI.
4. Confirm request-local stages no longer emit misleading drift warnings for
   ambient `/options` mismatch.

## Verification Criteria

### Success Criteria

1. ADetailer defaults to the global-switch path.
2. Request-local ADetailer pinning is opt-in only.
3. Deterministic ADetailer inference errors do not restart WebUI.
4. Ambient `/options` mismatch under request-local mode is logged as expected
   context, not as a misleading drift warning.

### Failure Criteria

1. ADetailer still defaults to request-local pinning.
2. The fix accidentally changes txt2img or upscale model-context behavior.
3. WebUI restart loops return for deterministic inference failures.
4. The PR widens into unrelated WebUI process-policy or GUI work.

## Risk Assessment

### Low-Risk Areas

- env-flag defaults and focused logging adjustments

### Medium-Risk Areas with Mitigation

- preserving the request-local debug path without letting it remain the default
  - Mitigation: explicit tests for default-off and opt-in-on behavior

### High-Risk Areas with Mitigation

- unintentionally changing shared executor behavior for non-ADetailer stages
  - Mitigation: keep the change fenced to ADetailer-specific paths and rerun
    targeted executor tests

### Rollback Plan

- revert to the prior ADetailer context-selection code and diagnostics if the
  finalized default-global path unexpectedly breaks working ADetailer cases

## Tech Debt Analysis

### Debt Removed

- unstable default ADetailer request-local pinning behavior
- misleading model-drift noise for request-local stage context
- restart churn for deterministic ADetailer inference failures if any cleanup is
  still needed during finalization

### Debt Intentionally Deferred

- broader WebUI launch-profile experimentation for ADetailer precision hardening
  - next PR owner: follow-on runtime hardening only if the default-global fix is
    insufficient

## Documentation Updates

- update `docs/Research Reports/D-016-Branch-Review-Since-2026-03-22-2205.md`
  only if the final landed behavior differs materially from the discovery note
- no canonical architecture docs should change in this PR unless the runtime
  truth differs from current canon, which is not expected

## Dependencies

### Internal Module Dependencies

- `src/pipeline/executor.py`
- `src/config/app_config.py`
- `src/api/client.py`

### External Tools or Runtimes

- A1111 WebUI runtime for optional manual verification
- `pytest`

## Approval & Execution

Planner: Codex
Executor: Codex
Reviewer: Human
Approval Status: Pending

## Next Steps

1. `PR-POLISH-282-Canonical-Roadmap-Video-Status-Harmonization`
2. end-to-end managed video runtime verification after the branch is stable

