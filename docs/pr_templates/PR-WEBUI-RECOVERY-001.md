# PR-WEBUI-RECOVERY-001: Expand WebUI Crash Detection and Recovery

**Status**: READY FOR IMPLEMENTATION  
**Priority**: HIGH  
**PR Type**: Resilience Enhancement  
**Architecture Impact**: None (extends existing retry mechanism)  
**Discovery**: D-WEBUI-001-Recovery-Architecture-Analysis.md

---

## Context & Motivation

StableNew has WebUI crash recovery mechanisms in `single_node_runner.py`, but they are too conservative, causing pipeline failures to be unrecoverable:

1. **Timeouts are explicitly excluded** from crash recovery (lines 95-100)
2. **HTTP 500 errors don't trigger restart** - only "connection refused" patterns do
3. **Only 2 retry attempts** before giving up (`_MAX_WEBUI_CRASH_RETRIES = 2`)

**Evidence from logs (Dec 24-25, 2025):**
- HTTP 500 cascade: txt2img returned 500 errors, 3 retries, no WebUI restart
- Timeout cascade: 5+ minutes of read timeouts, no restart triggered
- Jobs fail irrecoverably even though restart mechanism exists

---

## Root Cause Analysis

### Current Detection Logic (single_node_runner.py:77-116)

```python
_CRASH_MESSAGE_KEYWORDS = ("connection refused", "actively refused", "webui unavailable")
_TIMEOUT_KEYWORDS = ("read timed out", "readtimeout", "timeout", "timed out")

def _is_webui_crash_exception(exc: Exception) -> tuple[bool, str | None]:
    # Timeouts explicitly EXCLUDED from crash recovery
    if any(kw in error_message_lower for kw in _TIMEOUT_KEYWORDS):
        logger.info("Timeout detected but NOT treating as crash...")
        return False, stage_name  # ← NO RECOVERY!
    
    # Only connection errors trigger recovery
    if any(keyword in error_message_lower for keyword in _CRASH_MESSAGE_KEYWORDS):
        return True, stage_name  # ← Triggers restart
```

### Problem Summary

| Error Type | Current Behavior | Correct Behavior |
| ---------- | ---------------- | ---------------- |
| Connection refused | ✅ Triggers restart | ✅ Keep |
| HTTP 500 | ❌ No restart | ✅ Should restart |
| Single timeout | ❌ No restart | ✅ Keep (slow processing) |
| 3+ consecutive timeouts | ❌ No restart | ✅ Should restart (WebUI hung) |

---

## Implementation Plan

### Changes Overview

| Change | File | Risk | Description |
| ------ | ---- | ---- | ----------- |
| 1 | single_node_runner.py | LOW | Add HTTP 500 to crash keywords |
| 2 | single_node_runner.py | LOW | Track consecutive timeouts, escalate to crash |
| 3 | single_node_runner.py | LOWEST | Increase retry count from 2 to 4 |
| 4 | test_single_node_runner.py | NONE | Add tests for new patterns |

---

## Allowed Files

| File | Action | Rationale |
| ---- | ------ | --------- |
| `src/queue/single_node_runner.py` | MODIFY | Extend crash detection logic |
| `tests/queue/test_single_node_runner.py` | MODIFY | Add test coverage |

## Forbidden Files

| File | Rationale |
| ---- | --------- |
| `src/pipeline/pipeline_runner.py` | Out of scope - no architectural changes |
| `src/pipeline/executor.py` | Out of scope - diagnostics only |
| `src/api/client.py` | Out of scope - HTTP retry layer unchanged |

---

## Detailed Implementation

### Step 1: Expand Crash Message Keywords

**File**: `src/queue/single_node_runner.py`

**Before** (line 48):
```python
_CRASH_MESSAGE_KEYWORDS = ("connection refused", "actively refused", "webui unavailable")
```

**After**:
```python
_CRASH_MESSAGE_KEYWORDS = (
    "connection refused",
    "actively refused",
    "webui unavailable",
    "500 server error",         # PR-WEBUI-RECOVERY-001: HTTP 500
    "internal server error",    # PR-WEBUI-RECOVERY-001: HTTP 500 variant
)
```

### Step 2: Add Timeout Escalation Tracking

**File**: `src/queue/single_node_runner.py`

**Add new constant** (after line 50):
```python
# PR-WEBUI-RECOVERY-001: Consecutive timeouts before treating as crash
_TIMEOUT_ESCALATION_THRESHOLD = 3
```

**Add module-level counter** (after constants):
```python
# PR-WEBUI-RECOVERY-001: Track consecutive timeout failures per job
_consecutive_timeout_counts: dict[str, int] = {}
```

**Modify `_is_webui_crash_exception`** to track and escalate timeouts:

```python
def _is_webui_crash_exception(exc: Exception, job_id: str | None = None) -> tuple[bool, str | None]:
    """Determine if exception indicates WebUI crash requiring restart.
    
    PR-WEBUI-RECOVERY-001: Now tracks consecutive timeouts and escalates
    to crash status after _TIMEOUT_ESCALATION_THRESHOLD failures.
    """
    diag = _get_diagnostics_context(exc)
    if not diag:
        return False, None
    summary = diag.get("request_summary") or {}
    status = summary.get("status")
    method = (summary.get("method") or "").upper()
    attempt_stage = _select_request_summary_stage(summary)
    stage_name = attempt_stage or (getattr(exc, "stage", None) or summary.get("stage"))
    
    error_message_lower = str(diag.get("error_message") or exc).lower()
    exc_message_lower = str(exc).lower()
    
    # PR-WEBUI-RECOVERY-001: Check for timeout with escalation
    is_timeout = any(kw in error_message_lower or kw in exc_message_lower for kw in _TIMEOUT_KEYWORDS)
    if is_timeout:
        if job_id:
            _consecutive_timeout_counts[job_id] = _consecutive_timeout_counts.get(job_id, 0) + 1
            timeout_count = _consecutive_timeout_counts[job_id]
            if timeout_count >= _TIMEOUT_ESCALATION_THRESHOLD:
                logger.warning(
                    "PR-WEBUI-RECOVERY-001: %d consecutive timeouts for job %s, treating as crash",
                    timeout_count,
                    job_id,
                )
                return True, stage_name
        logger.info(
            "Timeout detected but NOT treating as crash (slow processing, not WebUI failure): %s",
            str(exc)[:200],
        )
        return False, stage_name
    
    # Reset timeout counter on non-timeout error
    if job_id and job_id in _consecutive_timeout_counts:
        del _consecutive_timeout_counts[job_id]
    
    # Existing crash detection logic
    try:
        status_code = int(status)
    except (TypeError, ValueError):
        status_code = None
    if (
        status_code == 500
        and method == "POST"
        and stage_name
        and stage_name.lower() in _CRASH_ELIGIBLE_STAGES
    ):
        return True, stage_name
    if diag.get("webui_unavailable"):
        if any(keyword in error_message_lower for keyword in _CRASH_MESSAGE_KEYWORDS):
            return True, stage_name
    message = str(exc).lower()
    if "webui unavailable" in message:
        return True, stage_name
    # PR-WEBUI-RECOVERY-001: Also check for HTTP 500 patterns in message
    if any(keyword in error_message_lower for keyword in _CRASH_MESSAGE_KEYWORDS):
        return True, stage_name
    return False, stage_name
```

**Update call site in `_run_with_webui_retry`** (line ~190):
```python
# Before:
crash_eligible, stage = _is_webui_crash_exception(exc)

# After:
crash_eligible, stage = _is_webui_crash_exception(exc, job_id=job.job_id)
```

**Add cleanup helper** (after `_run_with_webui_retry`):
```python
def _clear_timeout_tracking(job_id: str) -> None:
    """PR-WEBUI-RECOVERY-001: Clear timeout counter after job completes."""
    if job_id in _consecutive_timeout_counts:
        del _consecutive_timeout_counts[job_id]
```

**Call cleanup in finally block of `_worker_loop`** (line ~385):
```python
finally:
    self._current_job = None
    # PR-WEBUI-RECOVERY-001: Clear timeout tracking
    _clear_timeout_tracking(job.job_id)
    # Apply cooldown for reprocess jobs...
```

### Step 3: Increase Retry Count

**File**: `src/queue/single_node_runner.py`

**Before** (line 44):
```python
_MAX_WEBUI_CRASH_RETRIES = 2
```

**After**:
```python
_MAX_WEBUI_CRASH_RETRIES = 4  # PR-WEBUI-RECOVERY-001: Increased from 2 for better resilience
```

---

## Test Plan

### New Tests Required

**File**: `tests/queue/test_single_node_runner.py`

```python
class TestCrashDetectionPRWEBUIRECOVERY001:
    """Tests for PR-WEBUI-RECOVERY-001 crash detection expansion."""
    
    def test_http_500_triggers_crash_detection(self):
        """HTTP 500 Internal Server Error should trigger crash detection."""
        exc = Exception("500 Server Error: Internal Server Error for url: /sdapi/v1/txt2img")
        exc.diagnostics_context = {
            "request_summary": {"status": 500, "method": "POST", "stage": "txt2img"},
            "error_message": "500 Server Error: Internal Server Error",
        }
        is_crash, stage = _is_webui_crash_exception(exc, job_id="test-job")
        assert is_crash is True
        assert stage == "txt2img"
    
    def test_single_timeout_does_not_trigger_crash(self):
        """Single timeout should NOT trigger crash detection."""
        exc = Exception("Read timed out. (read timeout=10.0)")
        exc.diagnostics_context = {
            "request_summary": {"stage": "txt2img"},
            "error_message": "Read timed out",
        }
        is_crash, _ = _is_webui_crash_exception(exc, job_id="test-job")
        assert is_crash is False
    
    def test_consecutive_timeouts_trigger_crash(self):
        """3+ consecutive timeouts should trigger crash detection."""
        job_id = "timeout-test-job"
        exc = Exception("Read timed out. (read timeout=10.0)")
        exc.diagnostics_context = {
            "request_summary": {"stage": "txt2img"},
            "error_message": "Read timed out",
        }
        # First two timeouts: no crash
        assert _is_webui_crash_exception(exc, job_id=job_id)[0] is False
        assert _is_webui_crash_exception(exc, job_id=job_id)[0] is False
        # Third timeout: escalate to crash
        assert _is_webui_crash_exception(exc, job_id=job_id)[0] is True
        # Cleanup
        _clear_timeout_tracking(job_id)
    
    def test_increased_retry_count(self):
        """Verify retry count increased to 4."""
        assert _MAX_WEBUI_CRASH_RETRIES == 4
```

### Existing Tests

Run all existing tests to verify no regressions:
```bash
pytest tests/queue/test_single_node_runner.py -v
```

---

## Verification Checklist

- [ ] `_CRASH_MESSAGE_KEYWORDS` includes HTTP 500 patterns
- [ ] `_TIMEOUT_ESCALATION_THRESHOLD = 3` constant added
- [ ] `_consecutive_timeout_counts` dict added for tracking
- [ ] `_is_webui_crash_exception` updated with job_id parameter
- [ ] Timeout escalation logic implemented
- [ ] `_clear_timeout_tracking` helper added
- [ ] Cleanup called in `_worker_loop` finally block
- [ ] `_MAX_WEBUI_CRASH_RETRIES` changed from 2 to 4
- [ ] New tests pass
- [ ] Existing tests pass

---

## Rollback Plan

If issues occur, revert to original values:
1. `_MAX_WEBUI_CRASH_RETRIES = 2`
2. Remove HTTP 500 from `_CRASH_MESSAGE_KEYWORDS`
3. Remove timeout escalation logic

---

## Documentation Updates

Update `docs/D-WEBUI-001-Recovery-Architecture-Analysis.md` to mark fixes as implemented.

---

## Related Work

- **D-WEBUI-001**: Discovery document with full analysis
- **Future PR**: Pre-stage health check (separate scope)
- **Future PR**: Graceful degradation for partial job success
