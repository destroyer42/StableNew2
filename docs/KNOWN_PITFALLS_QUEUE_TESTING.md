# KNOWN_PITFALLS_QUEUE_TESTING.md
## StableNew V2 / V2.5 — Queue Testing Pitfalls & Correct Patterns (Lint-clean)

## 1. Overview
StableNew’s queue subsystem is intentionally asynchronous:
- Direct runs execute synchronously.
- Queued runs execute in a background worker thread.

This design is correct but introduces pitfalls for tests.

## 2. Pitfall: Race Condition Between submit_queued() and run_next_now()
Background runner may consume the queued job before run_next_now() runs.

### Correct Pattern
Use job_history polling, not run_next_now().

## 3. Pitfall: Asserting Status on the Original Job Object
Runner updates JobHistory’s job record, not the original object.

### Correct Pattern
Fetch job from history and assert terminal status.

## 4. Pitfall: Using sleep() Instead of Polling
Sleeping is flaky. Poll until completed.

## 5. Pitfall: Mixing Manual Queue Driving With Background Runner
Do not call run_next_now() after submit_queued().

## 6. Pitfall: Asserting Ordering Without Draining Queue Correctly
Submit one job, wait, then submit next.

## 7. Correct Architectural Driver Layer
Tests must drive through:
GUI V2 → AppController → PipelineController → JobService → Runner → WebUI Stub → JobHistory

## 8. Summary Checklist
Avoid races, stale job objects, sleeps, mixed drivers, and direct runner calls.

- Watchdog threads introduced in Phase 3 may cancel long-running jobs when resource caps fire; queue tests should expect cancellations triggered by `[WATCHDOG]` log entries rather than assuming a manual stop hook.
- Phase 4 OS-level containers may force-kill job children via `[CONTAINER]` log notifications; queue tests should allow brief `[CONTAINER] job=… kill_all invoked` spikes when jobs finish or when OS-level limits fire, but the queue status should still settle to a terminal state.
- Phase 5 adds the diagnostics dashboard and `[DIAG]` reports; queue tests should tolerate silent log interactions when the controller generates bundled diagnostics (manual button, watchdog violations, or exception hooks) without assuming they mutate queue state.

## Recommended Location
docs/testing/KNOWN_PITFALLS_QUEUE_TESTING.md
