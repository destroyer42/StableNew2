# PR-HARDEN-007: Post-Recovery Health Check Timeout Increase

**Status**: 🟡 Specification  
**Priority**: HIGH  
**Effort**: SMALL (< 1 day)  
**Phase**: Post-Phase 4 Hardening  
**Date**: 2026-03-17  

---

## Context & Motivation

### Problem Statement

When the executor attempts WebUI recovery (stop + restart), the process takes
approximately 20–80 seconds depending on the hardware and the models loaded.
The current `_check_webui_health_before_stage` method uses a fixed
`check_connection(timeout=5.0)`. If the next pipeline stage starts within the
WebUI's startup window (0–~19.8 seconds post-restart), the 5-second probe fires
during model loading, fails, and triggers *another* recovery attempt — which
kills the WebUI while it is in the middle of starting up.

### Observed Failure Chain From Logs

```text
T+0s:    ADetailer recovery initiated — WebUI stop + restart
T+40s:   WebUI process started (observed from logs)
T+45s:   Upscale stage begins (_check_webui_health_before_stage)
T+45s:   check_connection(timeout=5.0) → fails (WebUI still loading models)
T+50s:   Recovery attempt triggered for upscale stage
T+50s:   _attempt_webui_recovery() kills the still-starting WebUI process
T+50s:   WinError 10061 (connection refused) on next POST attempt
```

The root cause: the upscale stage's health check fires ~5 seconds after process
start, but WebUI is not ready for ~19.8 seconds.

### Why 5 Seconds Is Too Short

The WebUI loads:
- A VAE (~2–3s)
- The base model checkpoint (~8–12s)
- Any ControlNet/extension model (~2–5s)

Total: 12–20 seconds on the observed hardware. A 5-second timeout checks during
model loading, not after API readiness.

### Desired Behaviour

After a recovery attempt, the next stage's health check should:
1. Use a longer probe timeout (30 seconds).
2. Not immediately trigger a second recovery if the probe times out — instead
   retry the probe a few times before declaring failure.

### Reference

- Root cause analysis: session conversation 2026-03-17
- Related: `PR-HARDEN-005` and `PR-HARDEN-006`
- Files: `src/pipeline/executor.py` — `_check_webui_health_before_stage`,
  `_attempt_webui_recovery`

---

## Goals & Non-Goals

### ✅ Goals

1. Track a `_last_recovery_time` timestamp in the executor after any successful
   recovery attempt.
2. In `_check_webui_health_before_stage`, if a recent recovery was performed
   (within a configurable grace window, default 120 seconds), use
   `check_connection(timeout=30.0)` instead of the normal `timeout=5.0`.
3. Add unit tests for the conditional timeout selection.

### ❌ Non-Goals

1. Changing the recovery logic itself (stop/restart sequence).
2. Adding a polling loop inside the health check (keep it a single probe).
3. Configuring the timeout via the GUI or `ConfigManager` (hard-code the value —
   it can be promoted to config in a follow-up if needed).
4. Any changes to `src/api/client.py` — `check_connection` already accepts a
   timeout kwarg.

---

## Allowed Files

### ✅ Files to Modify

| File | Reason | Lines Changed (Est.) |
|------|--------|----------------------|
| `src/pipeline/executor.py` | Add `_last_recovery_time`; conditional timeout in health check | ~20 |
| `tests/pipeline/test_executor_health_check.py` | Test conditional timeout (create if absent) | ~50 |

### ❌ Forbidden Files (DO NOT TOUCH)

| File/Directory | Reason |
|----------------|--------|
| `src/api/client.py` | Already accepts `timeout` kwarg — no changes needed |
| `src/utils/retry_policy_v2.py` | Out of scope |
| `src/gui/` | No GUI changes |

---

## Implementation Plan

### Step 1: Add `_last_recovery_time` instance variable

**Modify**: `src/pipeline/executor.py`

In `__init__` (or wherever the executor's instance variables are initialised),
add:

```python
self._last_recovery_time: float | None = None
```

### Step 2: Set `_last_recovery_time` in `_attempt_webui_recovery`

Locate `_attempt_webui_recovery`. At the end of the method, after the recovery
succeeds (before returning), add:

```python
import time
self._last_recovery_time = time.monotonic()
```

If the method can also fail (raise an exception), ensure the timestamp is only
set on success paths.

### Step 3: Use extended timeout in `_check_webui_health_before_stage`

Define a module-level constant near the other timeout constants in `executor.py`:

```python
POST_RECOVERY_HEALTH_CHECK_TIMEOUT_SEC = 30.0
POST_RECOVERY_GRACE_WINDOW_SEC = 120.0
```

In `_check_webui_health_before_stage`, where `check_connection(timeout=...)` is
called, replace the hardcoded value with conditional logic:

```python
_in_recovery_window = (
    self._last_recovery_time is not None
    and (time.monotonic() - self._last_recovery_time) < POST_RECOVERY_GRACE_WINDOW_SEC
)
probe_timeout = (
    POST_RECOVERY_HEALTH_CHECK_TIMEOUT_SEC if _in_recovery_window else 5.0
)
connected = self.client.check_connection(timeout=probe_timeout)
```

**Important**: Read `_check_webui_health_before_stage` fully before editing. The
method structure must be preserved — only the timeout value changes.

### Step 4: Add unit tests

**Test A — Normal timeout used when no recovery:**  
`_last_recovery_time = None`. Assert `check_connection` called with `timeout ≤ 5.0`.

**Test B — Extended timeout used immediately after recovery:**  
`_last_recovery_time = time.monotonic()` (just now). Assert `check_connection`
called with `timeout == 30.0`.

**Test C — Normal timeout resumes after grace window expires:**  
`_last_recovery_time = time.monotonic() - 150.0` (past the 120s window). Assert
`check_connection` called with `timeout ≤ 5.0`.

---

## Testing Plan

### Unit Tests

- `test_health_check_uses_normal_timeout_before_recovery`
- `test_health_check_uses_extended_timeout_after_recovery`
- `test_health_check_reverts_to_normal_timeout_after_grace_window`

Using `patch("src.pipeline.executor.time")` to control `time.monotonic()` output.

### Regression Tests

```
pytest tests/pipeline/ -q --tb=short
```

Expected: no new failures beyond pre-existing baseline.

### Integration Validation

After a real job with ADetailer failure, the upscale stage should no longer
trigger a second recovery. This can be verified by observing that:
- No `_attempt_webui_recovery` is called for the upscale stage in the same job
  where ADetailer already triggered a recovery.
- The upscale probe succeeds once WebUI finishes model loading (within 30s).

---

## Verification Criteria

### ✅ Success Criteria

1. `_last_recovery_time` is set after every successful `_attempt_webui_recovery`.
2. `_check_webui_health_before_stage` uses `timeout=30.0` within 120s of recovery.
3. `_check_webui_health_before_stage` uses the normal `timeout=5.0` when no
   recent recovery has occurred.
4. All 3 new unit tests pass.
5. No regression in existing pipeline test suite.

### ❌ Failure Criteria

- Recovery loop triggered for a stage that begins within 30s of a prior recovery
  (30.0s probe timeout allows the WebUI to finish loading).
- `check_connection` called with `timeout=30.0` when no recovery has occurred
  recently (would slow down normal-path health checks).

---

## Risk Assessment

### Low Risk Areas

✅ **Backwards compatibility**: The change is purely conditional — normal-path
health checks are unaffected. The extended timeout only applies within the 120s
grace window after a recovery.

✅ **One-directional change**: Only the timeout value changes; the health check
call site, error handling, and recovery-triggering logic are unchanged.

### Medium Risk Areas

⚠️ **30-second probe blocks the pipeline thread**: If WebUI is genuinely down
(not just loading models), the normal-path 5s timeout would fail fast, but the
post-recovery 30s timeout will block for the full 30s before triggering recovery.

- **Mitigation**: This is acceptable because the whole point is to allow WebUI
  startup time after a recovery. If genuine failure occurs after the grace window,
  normal 5s probes resume. Net latency cost is bounded at 30s × 1 probe.

### High Risk Areas

None identified.

### Rollback Plan

Remove `_last_recovery_time`, the two constants, and the conditional logic.
Revert `check_connection` call to hardcoded `timeout=5.0`. No other files changed.

---

## Tech Debt Removed

✅ Race condition where any pipeline stage following a recovery would immediately
re-trigger another recovery, killing the WebUI during model loading.

## Tech Debt Added

One new instance variable (`_last_recovery_time`) and two module constants.
These are minimal and well-named.

**Net Tech Debt**: -1

---

## Architecture Alignment

### ✅ Enforces Architecture v2.6

All changes are in `src/pipeline/executor.py`. The health check and recovery
coordination is already the responsibility of the executor. No new modules or
cross-layer dependencies.

### ✅ No Dict-Based Config

The timeout values are defined as named module constants in `executor.py`, not
as runtime dict config. They can be promoted to `ConfigManager` in a future PR
if dynamic configuration is required.

---

## Dependencies

### Pre-requisites

- None strictly required, but intended to be implemented alongside PR-HARDEN-005
  and PR-HARDEN-006 for full remediation of the ADetailer stall failure chain.

### Internal

- `src/api/client.py`: `check_connection(timeout=...)` — already accepts timeout
  kwarg, no changes required.

---

## Timeline & Effort

### Breakdown

| Task | Effort | Notes |
|------|--------|-------|
| Add `_last_recovery_time` and constants | 10 min | ~5 lines |
| Update `_attempt_webui_recovery` to set timestamp | 15 min | ~3 lines |
| Update `_check_webui_health_before_stage` | 20 min | ~12 lines |
| Write 3 unit tests | 30 min | ~50 lines |
| Run test suite + verify | 15 min | |

**Total**: ~1.5 hours

---

## Approval & Sign-Off

**Planner**: GitHub Copilot (analysis 2026-03-17)  
**Executor**: Codex  
**Reviewer**: Rob (Human Owner)  

**Approval Status**: 🟡 Awaiting approval

---

## Next Steps

After this PR is merged:
→ Implement PR-HARDEN-008 (per-job pipeline timeout ceiling)
→ Full regression run across all hardening PRs in sequence
