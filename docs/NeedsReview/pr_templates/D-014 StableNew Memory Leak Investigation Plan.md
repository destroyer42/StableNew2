D-014 StableNew Memory Leak Investigation Plan.md
Status: Discovery Report
Created: 2025-12-16
Scope: Process lifecycle management, thread/subprocess cleanup, memory leak root cause analysis
Risk Level: HIGH (system stability, OOM crashes)

1. Problem Statement
Symptom: Python process remains alive after StableNew GUI closes, consuming ~150 KB/s until OOM.

Current State:

No visible Python task in environment
Process persists invisibly
Previous kill-on-size heuristic broke webui
No graceful shutdown mechanism
Impact:

System instability
Resource exhaustion
Potential data loss from forced kills
2. Root Cause Hypothesis Tree
2.1 Likely Culprits (High Probability)
A. Orphaned Worker Threads
QueueProcessor thread may not join on exit
History/learning background threads unclosed
File watchers or polling loops not terminated
B. Subprocess Leaks
ComfyUI/webui subprocesses not killed
Runner executor processes detached
GPU monitoring or inference processes orphaned
C. Event Loop Persistence
Qt event loop not properly exited
Async tasks pending in background
Signal handlers preventing clean exit
D. Resource Cleanup Failure
Open file handles (logs, history DB, cache)
Socket connections (webui API, monitoring)
Memory-mapped files or shared memory segments
2.2 Medium Probability
E. Third-Party Library Issues
Torch/CUDA context not released
PIL/Pillow image buffers retained
SQLAlchemy connection pool not closed
2.3 Low Probability
F. Circular References
Python GC unable to collect due to reference cycles
Qt object parent-child relationships blocking deletion
3. Diagnostic Strategy
Phase 1: Instrumentation (Identify Leak Source)
Goal: Determine which component is leaking memory.

Actions:

Add Memory Profiling

Install memory_profiler or tracemalloc
Log memory usage at key lifecycle points
Track allocations by module/function
Process Tree Analysis

Use psutil to enumerate all child processes on startup
Log subprocess PIDs to process_registry.json
On exit, verify all children terminated
Thread Registry

Maintain list of all spawned threads with names
Log thread lifecycle (start/join/timeout)
Verify zero non-daemon threads at exit
Resource Handle Audit

Track open files via psutil.Process().open_files()
Track network connections via psutil.Process().connections()
Log unclosed handles at shutdown
Phase 2: Controlled Testing
Test Cases:

Test	Action	Expected Leak	Purpose
T1	Launch GUI, close immediately	None	Baseline
T2	Launch, load PromptPack, close	Small	PromptPack cleanup check
T3	Launch, queue job (don't run), close	Small	Queue cleanup check
T4	Launch, run job to completion, close	Medium	Runner/subprocess check
T5	Launch, run job, cancel mid-execution, close	High	Cancellation cleanup check
T6	Launch, start webui, close	Medium	Webui subprocess check
Execution:

Run each test 3 times
Monitor process with psutil for 60s post-close
Record: peak memory, final memory, subprocess count, thread count
4. Remediation Design
4.1 Immediate Fix: Graceful Shutdown Manager
New Component: shutdown_coordinator.py

Responsibilities:

Register all cleanup handlers
Execute shutdown sequence in dependency order
Force-kill stragglers after timeout
Log all cleanup actions
Shutdown Sequence:
1. GUI signals shutdown (user clicks Exit)
   ↓
2. ShutdownCoordinator.initiate()
   ├─ Stop accepting new jobs
   ├─ Cancel running jobs (if configured)
   ├─ Wait for queue to drain (max 10s)
   └─ Proceed to cleanup
   ↓
3. Component Cleanup (parallel where safe)
   ├─ QueueProcessor.stop() + join(timeout=5s)
   ├─ HistoryManager.flush() + close()
   ├─ LearningManager.shutdown()
   ├─ All file handles .close()
   └─ All database connections .close()
   ↓
4. Subprocess Termination
   ├─ Send SIGTERM to all registered PIDs
   ├─ Wait 5s
   ├─ Send SIGKILL to survivors
   └─ Verify all dead via psutil
   ↓
5. Thread Cleanup
   ├─ Set all thread stop flags
   ├─ Join non-daemon threads (timeout=3s each)
   └─ Log any unkillable threads
   ↓
6. Qt Cleanup
   ├─ app.quit()
   ├─ processEvents() to flush queue
   └─ deleteLater() on main window
   ↓
7. Final Verification
   ├─ psutil.Process().children() == []
   ├─ threading.enumerate() == [MainThread]
   └─ Log shutdown complete

4.2 Architecture Changes Required
Files to Create:
core/shutdown_coordinator.py — Main shutdown orchestrator
core/process_registry.py — Subprocess tracking
core/thread_registry.py — Thread tracking
Files to Modify:
gui/main_window.py — Add Exit button, wire to shutdown
core/queue_processor.py — Add stop() method with join
core/history.py — Add flush() and close() methods
learning/manager.py — Add shutdown() method
main.py — Register atexit handler
Invariants to Enforce:
Every spawned thread MUST be registered
Every subprocess MUST be registered
Every file/DB handle MUST be closeable
Shutdown MUST complete in <30s or force-exit
4.3 Defensive Measures
Process Isolation:

Run webui/ComfyUI in separate process groups
Use subprocess.Popen(start_new_session=True) on Unix
Track PIDs in process_registry.json for recovery
Timeout-Based Force Exit:
def emergency_shutdown(timeout=30):
    """Last resort if graceful shutdown fails."""
    signal.alarm(timeout)  # Unix
    # or threading.Timer for cross-platform
    # If alarm fires, os._exit(1)

Leak Detection in Dev:

Enable tracemalloc in debug mode
Snapshot memory before/after operations
Fail CI tests if memory grows >10% in shutdown tests
5. Implementation Plan (PR Series)
PR-040: Shutdown Infrastructure
Scope: Add shutdown coordinator, registries, no behavioral changes yet
Files:

core/shutdown_coordinator.py (new)
core/process_registry.py (new)
core/thread_registry.py (new)
tests/test_shutdown.py (new)
Deliverable: Registries functional, coordinator skeleton exists

PR-041: Component Cleanup Methods
Scope: Add stop/close/shutdown methods to existing components
Files:

core/queue_processor.py — Add stop() with thread join
core/history.py — Add flush() and close()
learning/manager.py — Add shutdown()
tests/test_component_cleanup.py (new)
Deliverable: All components cleanly stoppable

PR-042: GUI Exit Button + Wiring
Scope: Add Exit button, wire to shutdown coordinator
Files:

gui/main_window.py — Add Exit button, connect signal
main.py — Register atexit handler
Update shutdown coordinator to orchestrate cleanup
Deliverable: Clicking Exit triggers graceful shutdown

PR-043: Subprocess Lifecycle Management
Scope: Track and kill subprocesses on exit
Files:

builders/comfyui_builder.py — Register subprocess
builders/webui_builder.py — Register subprocess
core/process_registry.py — Add kill methods
Deliverable: No orphaned ComfyUI/webui processes

PR-044: Memory Leak Diagnostics (Optional)
Scope: Add tracemalloc instrumentation for dev/debug
Files:

utils/memory_profiler.py (new)
main.py — Enable in debug mode
Deliverable: Memory leak detection in CI

6. Success Criteria
Deterministic Pass Conditions:

✅ All test cases (T1-T6) show zero leaked processes 60s post-close
✅ Memory growth <1 MB after shutdown (garbage collection noise only)
✅ psutil.Process().children() returns [] within 10s of exit
✅ threading.enumerate() shows only MainThread after exit
✅ No file handles remain open (via lsof on Linux or handle inspector on Windows)
✅ Shutdown completes in <10s for normal exit, <30s for force-exit
✅ CI test test_shutdown_no_leaks() passes 100 consecutive runs
Failure Conditions:

❌ Any orphaned process after 60s
❌ Memory growth >5 MB post-shutdown
❌ Shutdown timeout exceeded
❌ Crash or exception during shutdown
7. Risk Assessment
Risk	Likelihood	Impact	Mitigation
Shutdown hangs indefinitely	Medium	High	Force-exit timeout at 30s
Thread refuses to join	Low	Medium	Log warning, continue shutdown
Subprocess unkillable (zombie)	Low	Low	SIGKILL after SIGTERM timeout
Qt event loop blocks exit	Medium	High	Use app.quit() + processEvents()
Database corruption on force-kill	Low	Medium	Flush/commit before shutdown
8. Open Questions for Human
Cancellation Policy: Should running jobs be canceled on exit, or should we wait for completion?

Recommend: Wait max 10s, then cancel
Webui Behavior: Should webui process persist after GUI closes (server mode)?

Recommend: Kill webui by default, add --server-mode flag for persistence
Debug Logging: Enable verbose shutdown logging in production, or debug-only?

Recommend: Always log shutdown sequence to shutdown.log
Leak Tolerance: Acceptable memory leak threshold?

Recommend: <1 MB (GC noise), fail if >5 MB
9. Recommendation
Proceed with PR-040 → PR-043 series.

Rationale:

Addresses root cause (missing cleanup) vs. symptom (killing processes)
Low risk: changes are additive, no existing logic modified
Testable: clear pass/fail criteria
Incremental: can stop after any PR if issues arise
Estimated Effort:

PR-040: 2 hours (infrastructure)
PR-041: 3 hours (component changes + tests)
PR-042: 2 hours (GUI + wiring)
PR-043: 2 hours (subprocess tracking)
Total: ~9 hours over 4 PRs
Confidence: 95% success rate if executed per spec.

10. Next Steps
Human Decision Required:

Approve this discovery plan
Answer open questions (§8)
Authorize PR-040 execution
Then: I (ChatGPT) will generate PR-040 using PR_TEMPLATE_v2.6.md.

End of D-014 Discovery Report