# D-WEBUI-001: WebUI Recovery Architecture Analysis

**Status:** Discovery Complete  
**Date:** 2025-12-25  
**Author:** Copilot  
**Severity:** HIGH  
**Impact:** Pipeline fails irrecoverably when WebUI hangs or crashes  

---

## Executive Summary

StableNew has WebUI crash recovery mechanisms, but they have critical gaps that cause pipeline failures to be unrecoverable:

1. **Timeouts are excluded from recovery** - WebUI hangs (read timeouts) don't trigger restart
2. **HTTP 500 errors don't trigger restart** - Only "connection refused" patterns do
3. **No proactive health checks** - Pipeline assumes WebUI is healthy before each stage
4. **No graceful degradation** - One failed image fails entire job

---

## Current Architecture

### Retry Layers

```
┌─────────────────────────────────────────────────────────────────┐
│ SingleNodeRunner._run_with_webui_retry()                        │
│   └── Job-level retry (3 attempts max)                          │
│       └── Triggers WebUI restart on "crash" exceptions          │
│           └── ONLY for: connection refused, webui unavailable   │
│           └── EXCLUDES: timeouts, HTTP 500                      │
├─────────────────────────────────────────────────────────────────┤
│ SDWebUIClient._perform_request()                                │
│   └── HTTP-level retry (3 attempts per request)                 │
│       └── Exponential backoff with jitter                       │
│       └── No WebUI restart capability                           │
└─────────────────────────────────────────────────────────────────┘
```

### Key Files

| File | Role | Current State |
|------|------|---------------|
| `src/queue/single_node_runner.py` | Job retry + WebUI restart | Only triggers on connection errors |
| `src/api/client.py` | HTTP retry/backoff | No restart capability |
| `src/api/webui_process_manager.py` | WebUI lifecycle | Has `restart_webui()` |
| `src/pipeline/executor.py` | Stage execution | Rich diagnostics, no recovery |
| `src/utils/retry_policy_v2.py` | Retry config | Per-stage policies |

### Detection Logic (single_node_runner.py:77-116)

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

---

## Observed Failure Patterns

### Pattern 1: HTTP 500 Cascade (Dec 24, 17:39)

```
17:39:10 POST /sdapi/v1/txt2img → 500 Internal Server Error
17:39:12 Retry 2/3 → 500
17:39:14 Retry 3/3 → 500
17:39:14 PipelineStageError: txt2img error: WebUI returned no data
17:39:14 adetailer stage skipped: no input images
17:39:14 upscale stage skipped: no input images
```

**Root Cause:** WebUI was running but unstable. HTTP 500 doesn't match `_CRASH_MESSAGE_KEYWORDS`.

**Impact:** Job failed. No WebUI restart. No recovery possible.

### Pattern 2: Read Timeout Cascade (Dec 24, 17:44-17:49)

```
17:44:43 GET /sdapi/v1/sd-models → Read timed out (10.0s)
17:44:54 Retry 2/3 → Read timed out
17:45:06 Retry 3/3 → Read timed out
17:45:06 ERROR: Request failed after 3 attempts
[Continues for 5+ minutes across multiple endpoints]
```

**Root Cause:** WebUI was hung (likely GPU memory pressure). Timeouts are explicitly excluded.

**Impact:** All resource fetches failed. No restart triggered. User must manually intervene.

### Pattern 3: Cleanup-Triggered Crash (Dec 25, 01:35)

```
01:35:22 STARTING AGGRESSIVE WEBUI PROCESS CLEANUP
01:35:24 Found large python.exe process PID 49472 (3328.1 MB) - likely WebUI leak
01:35:24 ✓ Successfully killed PID 49472
01:35:24 ✓ Successfully killed PID 50204 (3458.0 MB)
01:35:37 GET /sdapi/v1/sd-models → connection refused
```

**Root Cause:** Memory leak cleanup killed WebUI. This WOULD trigger recovery if it happened during job execution.

---

## Proposed Solutions

### Solution 1: Expand Crash Detection (LOW RISK)

**Change:** Include HTTP 500 and persistent timeouts in crash detection.

```python
# In single_node_runner.py

_CRASH_MESSAGE_KEYWORDS = (
    "connection refused", 
    "actively refused", 
    "webui unavailable",
    "500 server error",        # NEW
    "internal server error",   # NEW
)

# Consider timeouts as crashes after N consecutive failures
_TIMEOUT_BECOMES_CRASH_AFTER = 3  # NEW

def _is_webui_crash_exception(exc: Exception) -> tuple[bool, str | None]:
    # ... existing detection logic ...
    
    # NEW: After 3 consecutive timeouts on same stage, treat as crash
    if timeout_detected and consecutive_timeout_count >= _TIMEOUT_BECOMES_CRASH_AFTER:
        return True, stage_name
```

**Risk:** LOW - Expands existing working mechanism.

### Solution 2: Pre-Stage Health Check (MEDIUM RISK)

**Change:** Check WebUI health before each stage, restart if unhealthy.

```python
# In pipeline_runner.py, before each stage

def _ensure_webui_ready(self, stage_name: str, max_attempts: int = 3) -> bool:
    """Verify WebUI is responsive before starting stage."""
    from src.api.webui_process_manager import get_global_webui_process_manager
    
    for attempt in range(max_attempts):
        if self._check_webui_health():
            return True
        
        logger.warning(f"WebUI not ready before {stage_name}, attempt {attempt+1}")
        manager = get_global_webui_process_manager()
        if manager:
            manager.restart_webui(wait_ready=True)
    
    return False
```

**Risk:** MEDIUM - Adds new code path, needs thorough testing.

### Solution 3: Graceful Degradation (HIGH VALUE)

**Change:** Allow partial job success - continue with remaining prompts if one fails.

```python
# In pipeline_runner.py

def _run_stage_with_fallback(self, stage, images, njr):
    try:
        return self._run_stage(stage, images, njr)
    except PipelineStageError as e:
        if e.is_recoverable and njr.variant_index < njr.variant_total - 1:
            logger.warning(f"Stage {stage.name} failed for variant {njr.variant_index}, continuing")
            return None  # Allow partial success
        raise
```

**Risk:** Requires careful consideration of job success/failure semantics.

### Solution 4: Increase Retry Attempts (LOWEST RISK)

**Change:** Increase `_MAX_WEBUI_CRASH_RETRIES` from 2 to 4.

```python
_MAX_WEBUI_CRASH_RETRIES = 4  # Was 2, now 5 total attempts
```

**Risk:** LOWEST - Simple constant change, existing mechanism.

---

## Recommended Implementation Order

| Priority | Solution | Effort | Risk | Impact |
|----------|----------|--------|------|--------|
| 1 | **Expand crash detection** | Low | Low | High - catches 500s and timeouts |
| 2 | **Increase retry count** | Trivial | Lowest | Medium - more resilience |
| 3 | **Pre-stage health check** | Medium | Medium | High - proactive recovery |
| 4 | **Graceful degradation** | High | Medium | Medium - partial success |

---

## Proposed PR: PR-WEBUI-RECOVERY-001

### Scope

1. **Expand `_CRASH_MESSAGE_KEYWORDS`** to include HTTP 500 patterns
2. **Add timeout escalation** - treat persistent timeouts as crashes
3. **Increase `_MAX_WEBUI_CRASH_RETRIES`** from 2 to 4
4. **Add pre-stage health check** with automatic restart

### Files to Modify

| File | Change |
|------|--------|
| `src/queue/single_node_runner.py` | Expand crash detection, increase retries |
| `src/pipeline/pipeline_runner.py` | Add pre-stage health check (optional) |
| `tests/queue/test_single_node_runner.py` | Add tests for new detection patterns |

### NOT in Scope

- Graceful degradation (separate PR)
- GUI recovery buttons (already exist)
- Process manager changes (already works)

---

## Test Plan

1. **Unit Tests:**
   - `test_http_500_triggers_crash_detection`
   - `test_persistent_timeout_triggers_crash_detection`
   - `test_single_timeout_does_not_trigger_crash`
   - `test_increased_retry_count`

2. **Integration Tests:**
   - Mock WebUI returning 500s → verify restart triggered
   - Mock WebUI timeouts → verify escalation to crash
   - Verify job succeeds after recovery

---

## Appendix: Log Evidence

### HTTP 500 Failure (logs/stablenew-20251224-173702.log)

```
2025-12-24 17:39:10,919 - HTTPError POST txt2img status=500: Internal Server Error
2025-12-24 17:39:12,342 - Request attempt 2/3 failed
2025-12-24 17:39:14,553 - Request attempt 3/3 failed
2025-12-24 17:39:14,558 - generate_images failed for txt2img: WebUI returned no data
```

### Timeout Cascade (logs/stablenew-20251224-174255.log)

```
2025-12-24 17:44:43,296 - Request sd-models attempt 1/3 failed: Read timed out
2025-12-24 17:44:54,458 - Request sd-models attempt 2/3 failed: Read timed out
2025-12-24 17:45:06,656 - Request sd-models failed after 3 attempts
[Continues for 5+ minutes...]
```

### Memory Cleanup (logs/stablenew-20251225-013148.log)

```
2025-12-25 01:35:22,913 - STARTING AGGRESSIVE WEBUI PROCESS CLEANUP
2025-12-25 01:35:24,482 - Found large python.exe PID 49472 (3328.1 MB) - likely WebUI leak
2025-12-25 01:35:24,485 - ✓ Successfully killed PID 49472
2025-12-25 01:35:24,485 - CLEANUP COMPLETE: Killed 8 WebUI-related processes
```

---

## Conclusion

The recovery mechanisms exist but are too conservative. By expanding crash detection to include HTTP 500s and escalating persistent timeouts, we can significantly improve pipeline resilience without major architectural changes.
