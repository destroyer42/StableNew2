# PR-HARDEN-005: Stall State Reset on WebUI Idle/Recovery

**Status**: 🟡 Specification  
**Priority**: CRITICAL  
**Effort**: SMALL (< 1 day)  
**Phase**: Post-Phase 4 Hardening  
**Date**: 2026-03-17  

---

## Context & Motivation

### Problem Statement

`_poll_progress_loop` tracks stall state in three variables: `highest_progress`,
`stall_first_detected_at`, and `interrupt_sent`. None of these ever reset when
WebUI restarts mid-call. The result is two interconnected failure modes:

**Failure Mode A — Spurious interrupt on healthy re-attempt:**
After recovery + retry, the new generation starts at progress 0.0. Because
`0.0 < highest_progress (0.677)` the code treats this as a progress regression
and ignores it. `stall_first_detected_at` remains at the old timestamp (now
minutes past `STALL_INTERRUPT_THRESHOLD_SEC`). If `interrupt_sent` were ever
reset (e.g., a future fix), the interrupt fires immediately against the healthy
re-attempt.

**Failure Mode B — Stale stall event poisons subsequent jobs:**
`stall_detected_event` is per-call, but `highest_progress`, `stall_first_detected_at`
and `interrupt_sent` are local to the poll thread — they ARE correctly scoped per
invocation of `_generate_images_with_progress`. However `interrupt_sent=True`
means no interrupt will fire on attempts 2, 3, or 4 (via retry + recovery retry)
even when the re-attempt also stalls. This was confirmed in logs where attempt 2/2
stalled for the full 120s without an interrupt.

### Why This Matters

After the original interrupt fix (PR-HARDEN-004 + this session), the interrupt fires
*once* at T+90s of the first attempt. If the HTTP retry (attempt 2) AND the
recovery retry both also stall, no interrupts are sent for those attempts, adding
up to 240s of additional unnecessary wait.

### Current Architecture

```
_generate_images_with_progress()
  └── _poll_progress_loop()       ← one thread per _generate_images_with_progress call
        ├── interrupt_sent = False  (initialised once)
        ├── stall_first_detected_at = None  (initialised once)
        └── highest_progress = 0.0  (initialised once)

_generate_images()
  └── _generate_images_with_recovery()
        └── client.generate_images()
              └── img2img()
                    └── _perform_request(max_attempts=2)
                          Attempt 1: 120s timeout → interrupt fires at 90s
                          backoff 1-2s
                          Attempt 2: 120s timeout → NO interrupt (interrupt_sent=True)
        If failed:
        └── _attempt_webui_recovery() → restart
        └── _generate_images_with_recovery(recovery_attempted=True)
              └── client.generate_images()
                    Attempt 1: 120s → NO interrupt
                    Attempt 2: 120s → NO interrupt
```

Total potential stall: 90s (interrupt) + 30s (attempt 1 drain) + 120s (attempt 2) +
restart (~40s) + 120s (recovery attempt 1) + 120s (recovery attempt 2) = **~520s**.

### Reference

- Root cause analysis: session conversation 2026-03-17
- Related: `PR-HARDEN-004` (original stall detection)
- Files affected: `src/pipeline/executor.py`

---

## Goals & Non-Goals

### ✅ Goals

1. Reset `stall_first_detected_at` and `interrupt_sent` when the poll loop detects
   that WebUI has become idle (`get_progress()` returns `None` or `progress == 0.0`
   with no active job).
2. Reset `highest_progress` to zero when WebUI is observed idle, so that a fresh
   generation starting from 0% is correctly tracked.
3. Ensure the interrupt fires on each independent generation attempt, not just the
   first, wherever the poll loop is still running.
4. Add unit test coverage for the reset path.

### ❌ Non-Goals

1. Changing recovery logic in `_generate_images_with_recovery`.
2. Changing retry policy counts (that is PR-HARDEN-006).
3. Adding per-attempt progress tracking (would require architectural changes).
4. Changing any GUI code.

---

## Allowed Files

### ✅ Files to Modify

| File | Reason | Lines Changed (Est.) |
|------|--------|----------------------|
| `src/pipeline/executor.py` | Reset stall state in `_poll_progress_loop` when WebUI goes idle | ~15 |
| `tests/pipeline/test_executor_progress_polling.py` | Add tests for idle-reset behaviour | ~60 |

### ❌ Forbidden Files (DO NOT TOUCH)

| File/Directory | Reason |
|----------------|--------|
| `src/api/client.py` | No changes needed here |
| `src/pipeline/pipeline_runner.py` | Out of scope |
| `src/gui/` | No GUI changes |
| Any `__init__.py` | No public API changes |

---

## Implementation Plan

### Step 1: Reset stall state on idle signal in `_poll_progress_loop`

**Modify**: `src/pipeline/executor.py`

In `_poll_progress_loop`, the current structure is:

```python
info = self.client.get_progress(skip_current_image=True)

if info is not None:
    if info.progress > highest_progress:
        ...
    # stall check
    elapsed_since_progress = ...
```

Change to:

```python
info = self.client.get_progress(skip_current_image=True)

if info is None:
    # WebUI is idle — either between jobs or has restarted.
    # Reset stall tracking so a fresh generation is not pre-judged as stalled.
    if stall_first_detected_at is not None or interrupt_sent:
        logger.debug(
            "Poll loop: WebUI idle signal received for %s — resetting stall state",
            stage_label,
        )
        stall_first_detected_at = None
        interrupt_sent = False
        highest_progress = 0.0
        last_progress_time = time.monotonic()
else:
    if info.progress > highest_progress:
        ...
    # stall check (unchanged)
```

This is the critical guard. When WebUI restarts, `get_progress()` returns `None`
(no active job). The next call after a fresh generation starts will return a non-None
ProgressInfo with progress starting from 0.0, which correctly exceeds the reset
`highest_progress = 0.0` and updates `last_progress_time`.

**Important:** The reset only fires when `stall_first_detected_at is not None or
interrupt_sent` — i.e., only when a stall was previously detected. If WebUI is simply
idle at the start of a run, this is a no-op.

### Step 2: Add unit tests

**Modify**: `tests/pipeline/test_executor_progress_polling.py`

Add a new test class `TestStallStateReset` with three tests:

**Test A — Reset fires on None after stall:**  
Use `PROGRESS_STALL_THRESHOLD_SEC=0.0`. Return progress 0.5 (stall detected), then
return `None` (WebUI idle), then return progress 0.3 (new generation). Assert that
`interrupt` is NOT called on the new 0.3 progress (stall was reset). Assert log message
contains "resetting stall state".

**Test B — No spurious reset on None before any stall:**  
Return `None` immediately (WebUI hasn't started yet). Assert `interrupt` is never
called even with `STALL_INTERRUPT_THRESHOLD_SEC=0.0`, because `stall_first_detected_at`
was never set.

**Test C — Interrupt fires again after reset:**  
Return progress 0.5 → stall triggers interrupt → return `None` (reset) → return
progress 0.3 (new attempt) → freeze at 0.3 → second stall triggers second interrupt.
Assert `interrupt` called exactly twice.

---

## Testing Plan

### Unit Tests

- `TestStallStateReset::test_stall_state_resets_on_webui_idle`
- `TestStallStateReset::test_no_spurious_reset_before_stall_detected`
- `TestStallStateReset::test_interrupt_fires_again_after_idle_reset`

All tests use `patch("src.pipeline.executor.PROGRESS_STALL_THRESHOLD_SEC", 0.0)` and
`patch("src.pipeline.executor.STALL_INTERRUPT_THRESHOLD_SEC", 0.0)` to avoid real
time dependency.

### Regression Tests

Run full pipeline test suite after change:
```
pytest tests/pipeline/ -q --tb=short
```
Expected: 4 failed + 2 errors (pre-existing), no new regressions.

### Manual Testing

Observe generation logs — after a recovery+restart, subsequent stall warnings for the
new generation should start from elapsed=0, not continue from the previous stall's
elapsed counter.

---

## Verification Criteria

### ✅ Success Criteria

1. All 3 new unit tests pass.
2. Full pipeline test suite shows no new failures beyond pre-existing 4 failed + 2 errors.
3. `_poll_progress_loop` stall state resets when `get_progress()` returns `None` after
   a stall has been detected.
4. Interrupt fires on attempt 2 and recovery attempts if they also stall (verified by
   Test C above).

### ❌ Failure Criteria

- Any regression in `tests/pipeline/test_executor_progress_polling.py`.
- `interrupt` being called during a healthy generation that follows a stall+idle cycle
  (would indicate the reset incorrectly re-arms the interrupt before a new stall).

---

## Risk Assessment

### Low Risk Areas

✅ **Polling loop logic**: Change is additive — new `if info is None` branch does not
modify the existing `if info is not None` block.

✅ **Thread safety**: All variables modified are local to the poll thread function.
No shared state involved.

### Medium Risk Areas

⚠️ **Idle detection accuracy**: `get_progress()` returning `None` is used as the
"WebUI idle" signal. It can also return `None` during transient network errors. The
reset guard (`stall_first_detected_at is not None or interrupt_sent`) mitigates this
— a transient None before any stall was detected is a no-op.

- **Mitigation**: The guard condition ensures the reset only fires when the poll loop
  has already entered stall territory, making false resets from transient None responses
  benign (worst case: stall clock resets by a few seconds, meaning one extra polling
  cycle before re-detection).

### High Risk Areas

None identified.

### Rollback Plan

Revert the `if info is None` block in `_poll_progress_loop`. The behaviour reverts
to the pre-fix state (stall state never resets, interrupt only fires once per
`_generate_images_with_progress` call).

---

## Tech Debt Removed

✅ Stall state being permanently poisoned by the first detected stall, preventing
subsequent interrupt-based recovery for retries and recovery attempts.

## Tech Debt Added

None.

**Net Tech Debt**: -1

---

## Architecture Alignment

### ✅ Enforces Architecture v2.6

Change is confined to `_poll_progress_loop` — a background thread helper within
the `Pipeline` executor. No changes to job path, NJR, queue, or runner.

### ✅ Follows Testing Standards

All tests are deterministic, use mocks, no real network calls, no sleeps beyond
the real-time threaded tests that patch thresholds to zero.

### ✅ Maintains Separation of Concerns

Poll loop concerns remain in poll loop. No cross-cutting changes.

---

## Dependencies

### External

None.

### Internal

- `src/api/client.py`: `PROGRESS_STALL_THRESHOLD_SEC`, `STALL_INTERRUPT_THRESHOLD_SEC`
  (already imported in executor.py after PR-HARDEN-004 work)

---

## Timeline & Effort

### Breakdown

| Task | Effort | Notes |
|------|--------|-------|
| Modify `_poll_progress_loop` | 30 min | ~15 lines |
| Write 3 unit tests | 45 min | ~60 lines |
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
→ Implement PR-HARDEN-006 (ADetailer retry policy reduction)
→ Implement PR-HARDEN-007 (post-recovery health check timeout)
