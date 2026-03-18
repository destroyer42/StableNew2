# PR-HARDEN-006: ADetailer-Specific Retry Policy (Fail-Fast on Hung Stage)

**Status**: 🟡 Specification  
**Priority**: HIGH  
**Effort**: SMALL (< 1 day)  
**Phase**: Post-Phase 4 Hardening  
**Date**: 2026-03-17  

---

## Context & Motivation

### Problem Statement

ADetailer inpainting (`img2img` triggered by the adetailer plugin) is treated as
a generic `img2img` operation by the retry policy. `IMG2IMG_RETRY_POLICY` allows
`max_attempts=2`, meaning after a stall+timeout, the same hung operation is retried
immediately. In practice, a GPU OOM loop inside ADetailer will hang every attempt
for exactly `DEFAULT_GENERATION_TIMEOUT = 120.0` seconds.

Current worst-case timeline (adetailer path with 2 attempts + recovery retry):

```
Attempt 1: ADetailer OOM at T+90s → interrupt fires → HTTP keeps waiting → timeout at T+120s
Attempt 2: Retry — exactly same OOM → NO interrupt (interrupt_sent=True) → times out at T+240s
Recovery: WebUI restarts (~40s)
Recovery attempt 1: 120s timeout
Recovery attempt 2: 120s timeout
────────────────────────────────────────────────────────────────────
Total ADetailer stall cost: ~620s per failed job (after PR-HARDEN-005)
```

With a max_attempts=1 ADetailer policy, the retry is eliminated. Combined with
PR-HARDEN-005 (stall state reset), the interrupt fires on the recovery attempt too,
truncating the full stall to:

```
Attempt 1: OOM → interrupt at T+90s → HTTP drains → timeout at ~T+120s
Recovery: WebUI restarts (~40s)
Recovery attempt 1: OOM → interrupt at T+90s → HTTP drains → timeout at ~T+120s
────────────────────────────────────────────────────────────────────
Total ADetailer stall cost: ~370s (vs ~620s), saves ~250s per job
```

Further reduction comes from PR-HARDEN-007 (health check prevents upscale collision).

### Why Retry Doesn't Help ADetailer OOM Loops

An ADetailer `img2img` is hung because PyTorch's VRAM allocator has entered a retry
loop (allocate → fail → wait → retry). This condition persists until:
1. GPU memory is freed by a full WebUI restart, OR  
2. `/sdapi/v1/interrupt` breaks the inference loop

A same-process immediate retry (attempt 2) will hit the same VRAM pressure since no
memory was freed between attempts. The second attempt is guaranteed to hang. There is
no scenario where retrying without a restart helps ADetailer OOM.

For non-OOM transient errors (socket resets, temporary timeouts), the WebUI-level
recovery (restart) already provides a structural retry at the outer level.

### Reference

- Root cause analysis: session conversation 2026-03-17
- Related: `PR-HARDEN-005` (stall state reset — implement first)
- ADetailer plugin v25.3.0; WebUI v1.10.1

---

## Goals & Non-Goals

### ✅ Goals

1. Define `ADETAILER_RETRY_POLICY` with `max_attempts=1` in
   `src/utils/retry_policy_v2.py`.
2. Register `STAGE_RETRY_POLICY["adetailer"]` in the retry policy registry.
3. Ensure the ADetailer code path in `executor.py` passes `stage="adetailer"` so
   it uses the correct policy instead of `"img2img"`.
4. Unit test coverage for the new policy being selected and respected.

### ❌ Non-Goals

1. Changing the outer recovery/restart logic.
2. Changing `IMG2IMG_RETRY_POLICY` for non-ADetailer img2img calls.
3. Changing `TXT2IMG_RETRY_POLICY`.
4. GUI changes of any kind.
5. Reducing the `DEFAULT_GENERATION_TIMEOUT` (that is a separate trade-off).

---

## Allowed Files

### ✅ Files to Modify

| File | Reason | Lines Changed (Est.) |
|------|--------|----------------------|
| `src/utils/retry_policy_v2.py` | Add `ADETAILER_RETRY_POLICY`; add to stage registry | ~8 |
| `src/pipeline/executor.py` | Pass `stage="adetailer"` from ADetailer code path | ~3 |
| `tests/utils/test_retry_policy.py` | Test new policy (or create if absent — see Step 3) | ~40 |

### ❌ Forbidden Files (DO NOT TOUCH)

| File/Directory | Reason |
|----------------|--------|
| `src/api/client.py` | No changes needed (stage routing already keyed to string) |
| `src/pipeline/pipeline_runner.py` | Out of scope |
| `src/gui/` | No GUI changes |

---

## Implementation Plan

### Step 1: Add `ADETAILER_RETRY_POLICY` to `retry_policy_v2.py`

**Modify**: `src/utils/retry_policy_v2.py`

After the `IMG2IMG_RETRY_POLICY` definition, add:

```python
# ADetailer img2img inpainting: fail-fast, no retry.
# A hung ADetailer call is due to GPU OOM — retrying without a restart
# guarantees the same stall. The outer recovery path provides structural retry.
ADETAILER_RETRY_POLICY = RetryPolicy(
    max_attempts=1,
    base_delay_sec=0.0,
    max_delay_sec=0.0,
    jitter_frac=0.0,
)
```

Also update `STAGE_RETRY_POLICY` dict to include the adetailer key:

```python
STAGE_RETRY_POLICY: dict[str, RetryPolicy] = {
    "txt2img": TXT2IMG_RETRY_POLICY,
    "img2img": IMG2IMG_RETRY_POLICY,
    "adetailer": ADETAILER_RETRY_POLICY,   # ← add this line
    "upscale": UPSCALE_RETRY_POLICY,
    "interrogate": INTERROGATE_RETRY_POLICY,
}
```

(If `STAGE_RETRY_POLICY` does not currently include `"upscale"` and `"interrogate"`,
only add `"adetailer"` — do not speculatively add other keys.)

### Step 2: Pass `stage="adetailer"` in executor.py ADetailer path

**Modify**: `src/pipeline/executor.py`

Locate the section of `_run_adetailer` (or the equivalent method that calls
`client.generate_images()` for ADetailer) where `stage=` is passed as a kwarg.
Change `stage="img2img"` to `stage="adetailer"`.

If the ADetailer path calls `client.img2img()` directly (not via `generate_images`),
locate where `retry_policy` is resolved and ensure the `"adetailer"` key is used.

**Important**: Confirm the exact method and call site by reading `executor.py` before
editing. Do not change any other `stage=` argument.

### Step 3: Add unit tests

The test file `tests/utils/test_retry_policy.py` may need to be created if absent.

**Test A — Policy selection:**  
Assert `STAGE_RETRY_POLICY["adetailer"] is ADETAILER_RETRY_POLICY`.

**Test B — Policy values:**  
Assert `ADETAILER_RETRY_POLICY.max_attempts == 1`, `base_delay_sec == 0.0`.

**Test C — No retry on adetailer failure (integration):**  
Using the existing `TestStallInterrupt`-style approach, mock `client.img2img` to
raise `WebUIUnavailableError` on the first call. Assert it is called exactly 1 time
(not 2) when the executor uses the adetailer stage.

---

## Testing Plan

### Unit Tests

- `test_adetailer_policy_registered_in_stage_map`
- `test_adetailer_policy_is_fail_fast`
- `test_adetailer_img2img_not_retried_on_failure`

### Regression Tests

```
pytest tests/pipeline/ tests/utils/ -q --tb=short
```

Expected: no new failures beyond pre-existing baseline.

### Manual Testing

Run a job that triggers ADetailer on an image that would cause an OOM (or simulate
by mocking). Observe that the ADetailer stage fails with a single attempt, then
triggers the outer recovery path, rather than a retry.

---

## Verification Criteria

### ✅ Success Criteria

1. `STAGE_RETRY_POLICY["adetailer"]` resolves to `ADETAILER_RETRY_POLICY`.
2. `ADETAILER_RETRY_POLICY.max_attempts == 1`.
3. ADetailer `img2img` call in executor passes `stage="adetailer"`.
4. All 3 new unit tests pass.
5. No regression in existing test suite.

### ❌ Failure Criteria

- ADetailer path still uses `stage="img2img"` after the change.
- `IMG2IMG_RETRY_POLICY.max_attempts` changed (must remain 2).

---

## Risk Assessment

### Low Risk Areas

✅ **Retry policy registry**: Adding a key to a dict is non-breaking for all
existing call sites that use `"txt2img"` or `"img2img"`.

✅ **Correctness**: `max_attempts=1` means exactly one attempt — the same behaviour
as `max_attempts=2` on the first call, except the retry is skipped.

### Medium Risk Areas

⚠️ **Finding the exact call site**: The ADetailer path in `executor.py` may not
be a clearly labelled method. The executor must be read carefully before making
the stage string change.

- **Mitigation**: Read `executor.py` fully before editing. Search for `adetailer`
  strings and `img2img` call patterns within the adetailer handling block.

### High Risk Areas

None identified.

### Rollback Plan

Remove `"adetailer": ADETAILER_RETRY_POLICY` from `STAGE_RETRY_POLICY` and revert
`stage="img2img"` in executor.py. Delete `ADETAILER_RETRY_POLICY` constant. Behaviour
reverts to 2-attempt policy.

---

## Tech Debt Removed

✅ ADetailer silently sharing the `img2img` retry policy with no logical basis —
the two operation classes have fundamentally different failure modes.

## Tech Debt Added

None.

**Net Tech Debt**: -1

---

## Architecture Alignment

### ✅ Enforces Architecture v2.6

Retry policy is a utility class; stage strings flow through the existing
`STAGE_RETRY_POLICY` registry already in use. No new control paths added.

### ✅ No GUI Involvement

All changes are in `src/utils/` and `src/pipeline/`, matching the architecture
requirement that stage routing logic is not in the GUI.

---

## Dependencies

### Pre-requisites

- PR-HARDEN-005 should be merged first, or merged simultaneously, so that the stall
  state reset and fail-fast retry work together correctly. They are independent at
  the code level but their benefit is maximised in combination.

### Internal

- `src/utils/retry_policy_v2.py`: provides `RetryPolicy`, `STAGE_RETRY_POLICY`
- `src/pipeline/executor.py`: consumes retry policy via stage string

---

## Timeline & Effort

### Breakdown

| Task | Effort | Notes |
|------|--------|-------|
| Add `ADETAILER_RETRY_POLICY` to `retry_policy_v2.py` | 15 min | ~8 lines |
| Locate and update `stage=` in `executor.py` | 30 min | Read before edit |
| Write 3 unit tests | 30 min | ~40 lines |
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
→ Implement PR-HARDEN-007 (post-recovery health check timeout)
→ Implement PR-HARDEN-008 (per-job pipeline timeout ceiling)
