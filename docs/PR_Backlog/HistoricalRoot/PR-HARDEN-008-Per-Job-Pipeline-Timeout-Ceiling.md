# PR-HARDEN-008: Per-Job Pipeline Timeout Ceiling (Dead-Man Switch)

**Status**: 🟡 Specification  
**Priority**: MEDIUM  
**Effort**: SMALL–MEDIUM (1–2 days)  
**Phase**: Post-Phase 4 Hardening  
**Date**: 2026-03-17  

---

## Context & Motivation

### Problem Statement

There is no hard ceiling on how long a single job may take to execute. Pipeline
stages can individually timeout and retry, recovery attempts have their own
timeouts, but nothing caps the total wall-clock time of the entire job. In the
failure scenario documented in `D-WEBUI-001`:

- ADetailer stalls for ~620s (before PR-HARDEN-005/006)
- Upscale triggers second recovery
- Net job duration: ~900s (15 minutes)

Even after PRs 005–007 reduce the worst case to ~370–450s, a pathological failure
(e.g., two-stage ADetailer on a multi-image batch, two consecutive OOM loops) could
still exceed 700s. Any scenario where a job hangs indefinitely (e.g., a future bug
where interrupt fails to fire) would block the queue forever.

A per-job timeout provides a last-resort safety net: after `N` seconds of total
pipeline execution, the job is forcibly failed and the queue can proceed to the
next job.

### Scope of Change

The deadline check should be evaluated before each pipeline stage begins. If the
deadline is exceeded, a `PipelineJobTimeoutError` is raised, the job is marked
failed, and the queue moves on. This does not replace stage-level timeouts — it
is a complementary ceiling.

### Reference

- Root cause analysis: session conversation 2026-03-17
- Related: `PR-HARDEN-005`, `PR-HARDEN-006`, `PR-HARDEN-007`
- Files: `src/pipeline/pipeline_runner.py`, `src/pipeline/executor.py`

---

## Goals & Non-Goals

### ✅ Goals

1. Define `DEFAULT_JOB_TIMEOUT_SEC = 600.0` constant (10 minutes) in
   `src/pipeline/pipeline_runner.py` or a shared constants module.
2. Record `job_start_time = time.monotonic()` when a job begins execution.
3. Before each pipeline stage call (`txt2img`, `adetailer`, `upscale`), check
   elapsed time against the deadline. If exceeded, raise `PipelineJobTimeoutError`.
4. `PipelineJobTimeoutError` should result in the job being marked as failed in
   history (same as other pipeline failures).
5. Unit tests covering deadline expiry before each stage type.

### ❌ Non-Goals

1. Configuring `max_job_timeout_seconds` via the GUI (hard-coded default, can be
   promoted to config in a later PR).
2. Graceful interruption of an in-progress stage if the deadline fires mid-stage
   (the check is pre-stage only — this PR is about preventing runaway jobs from
   blocking the queue).
3. Per-stage granular timeouts (that is the existing `DEFAULT_GENERATION_TIMEOUT`).
4. Any changes to history or learning subsystems.

---

## Allowed Files

### ✅ Files to Modify

| File | Reason | Lines Changed (Est.) |
|------|--------|----------------------|
| `src/pipeline/pipeline_runner.py` | Add job start time, pre-stage deadline check | ~25 |
| `src/pipeline/executor.py` | (Optional) Expose deadline to executor if check is done there | ~10 |
| `tests/pipeline/test_pipeline_runner.py` | Test deadline expiry path | ~60 |

### ❌ Forbidden Files (DO NOT TOUCH)

| File/Directory | Reason |
|----------------|--------|
| `src/queue/` | Queue receives the error and handles it normally — no changes |
| `src/history/` | Already records PipelineStageError failures |
| `src/gui/` | No GUI changes |
| `src/api/client.py` | Out of scope |

---

## Implementation Plan

### Step 1: Define `PipelineJobTimeoutError`

If not already in `src/pipeline/exceptions.py` (or equivalent), add:

```python
class PipelineJobTimeoutError(PipelineStageError):
    """Raised when a job exceeds the maximum allowed wall-clock time."""
```

If there is no `exceptions.py`, define it in `pipeline_runner.py` or `executor.py`
alongside existing exception classes. Check existing code before deciding.

### Step 2: Add module constant

In `src/pipeline/pipeline_runner.py` (near the top with other constants):

```python
# Maximum wall-clock duration for a single job end-to-end.
# Acts as a dead-man switch: prevents queue blockage from runaway jobs.
DEFAULT_JOB_TIMEOUT_SEC: float = 600.0
```

### Step 3: Record job start time

In `PipelineRunner._run_job` (or equivalent method that drives a single job),
record the start time:

```python
job_start_time: float = time.monotonic()
```

### Step 4: Pre-stage deadline check helper

Add a private method or inline check before each stage:

```python
def _check_job_deadline(
    self,
    job_start_time: float,
    stage_name: str,
    timeout_sec: float = DEFAULT_JOB_TIMEOUT_SEC,
) -> None:
    elapsed = time.monotonic() - job_start_time
    if elapsed >= timeout_sec:
        raise PipelineJobTimeoutError(
            stage=stage_name,
            message=(
                f"Job exceeded maximum duration of {timeout_sec:.0f}s "
                f"(elapsed: {elapsed:.1f}s) before stage '{stage_name}'"
            ),
        )
```

### Step 5: Insert deadline check before each stage

Locate the stage dispatch in `PipelineRunner` (the section that calls executor
methods for `txt2img`, `adetailer`, `upscale`, etc.). Before each stage call,
insert:

```python
self._check_job_deadline(job_start_time, stage_name="<stage>")
```

**Important**: Only the pre-stage check. Do not interrupt mid-stage.

### Step 6: Add unit tests

**Test A — No timeout when stages complete quickly:**  
Mock all stage calls to succeed instantly. Assert `PipelineJobTimeoutError` is
NOT raised.

**Test B — Timeout before adetailer stage:**  
Set `DEFAULT_JOB_TIMEOUT_SEC = 0.0` (or patch it). Assert `PipelineJobTimeoutError`
is raised before the adetailer stage and the upscale stage is never called.

**Test C — Timeout before upscale stage:**  
Fast txt2img + adetailer, then patch time.monotonic() to return a future value
that exceeds the deadline before the upscale check. Assert `PipelineJobTimeoutError`
raised with `stage="upscale"`.

**Test D — Job failure is recorded in history:**  
Assert that `PipelineJobTimeoutError` is caught by the same error path as
`PipelineStageError` and results in a `failed` job record.

---

## Testing Plan

### Unit Tests

- `test_no_timeout_on_fast_job`
- `test_timeout_raised_before_adetailer`
- `test_timeout_raised_before_upscale`
- `test_timeout_job_recorded_as_failed`

### Regression Tests

```
pytest tests/pipeline/ -q --tb=short
```

Expected: no new failures beyond pre-existing baseline.

### Manual Validation

Add a temporary log of elapsed time at each stage dispatch. Confirm for a normal
job that `elapsed < 600s` and no `PipelineJobTimeoutError` is emitted.

---

## Verification Criteria

### ✅ Success Criteria

1. `PipelineJobTimeoutError` exists and inherits from the correct base exception.
2. `DEFAULT_JOB_TIMEOUT_SEC = 600.0` defined as a named constant.
3. Deadline check fires before each stage, not mid-stage.
4. A job that exceeds the deadline is marked failed and the queue continues.
5. All 4 new unit tests pass.
6. Normal (fast) jobs are unaffected.

### ❌ Failure Criteria

- Queue blocks indefinitely when `PipelineJobTimeoutError` is raised (means
  exception is not caught at the right level).
- `PipelineJobTimeoutError` raised during a running stage (check must be
  pre-stage only).

---

## Risk Assessment

### Low Risk Areas

✅ **Pre-stage only**: The deadline check never interrupts a running stage.
Worst case: the check fires at the start of a valid stage unnecessarily (e.g.,
a legitimate 601-second job). For current workloads, 600s far exceeds the longest
normal job (~180s with ADetailer).

✅ **No new dependencies**: Uses `time.monotonic()` and standard Python exception
hierarchy.

### Medium Risk Areas

⚠️ **Exception propagation path**: `PipelineJobTimeoutError` must be handled at
the same level as other `PipelineStageError` subclasses. If the catch block only
catches the base class, this works automatically. Read the exception handling in
`pipeline_runner.py` before implementing.

- **Mitigation**: If `PipelineJobTimeoutError(PipelineStageError)` is used, it
  is caught everywhere `PipelineStageError` is caught. This is the safest
  inheritance structure.

⚠️ **Deadline value choice**: 600s is conservative. If a large batch job
legitimately takes 700s, the ceiling would fire incorrectly.

- **Mitigation**: 600s covers the current worst observed case + 2× safety margin.
  The constant can be tuned or promoted to a config value in a follow-up PR. Add
  a comment explaining the rationale.

### High Risk Areas

None identified.

### Rollback Plan

Remove the `_check_job_deadline` calls, the `PipelineJobTimeoutError` class, and
the `DEFAULT_JOB_TIMEOUT_SEC` constant. No queued-job format or NJR changes,
so rollback is clean.

---

## Tech Debt Removed

✅ The queue had no protection against a runaway job blocking it indefinitely.

## Tech Debt Added

One new constant, one new exception class, ~25 lines in pipeline_runner. Minimal.

**Net Tech Debt**: -1

---

## Architecture Alignment

### ✅ Enforces Architecture v2.6

`PipelineRunner` is the correct place for job-level orchestration. Stage-level
concerns live in `executor.py`. A job-level timeout ceiling belongs in the runner.

### ✅ NJR Contract Preserved

`NormalizedJobRecord` is not modified. The deadline check operates on wall-clock
time only, not on job data.

### ✅ Queue Contract Preserved

The queue receives a normal failure (job marked failed, queue continues). The
queue does not need to know about `PipelineJobTimeoutError` specifically.

---

## Dependencies

### Pre-requisites

- No strict ordering dependency, but intended to be implemented last in the
  hardening series after PR-HARDEN-005, 006, 007. Those PRs reduce the frequency
  of the timeout firing in practice; this PR handles the residual worst case.

### Internal

- `src/pipeline/pipeline_runner.py`: primary change location
- `src/pipeline/exceptions.py` (or wherever pipeline exceptions are defined)

---

## Timeline & Effort

### Breakdown

| Task | Effort | Notes |
|------|--------|-------|
| Research exception hierarchy, find PipelineStageError location | 20 min | Read-only |
| Add `PipelineJobTimeoutError` | 10 min | ~6 lines |
| Add constant + `job_start_time` recording | 10 min | ~4 lines |
| Add `_check_job_deadline` + insert calls | 30 min | ~15 lines |
| Write 4 unit tests | 45 min | ~60 lines |
| Run test suite + verify | 15 min | |

**Total**: ~2 hours

---

## Approval & Sign-Off

**Planner**: GitHub Copilot (analysis 2026-03-17)  
**Executor**: Codex  
**Reviewer**: Rob (Human Owner)  

**Approval Status**: 🟡 Awaiting approval

---

## Next Steps

After all four PRs (005–008) are implemented:
→ Run full regression suite (`pytest -q`)
→ Perform end-to-end manual test with ADetailer enabled on a batch job
→ Confirm stall spam eliminated, upscale race condition gone, queue proceeds normally
→ Update `D-WEBUI-001-Recovery-Architecture-Analysis.md` to mark issues as resolved
