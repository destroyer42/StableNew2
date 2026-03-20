# Known Pitfalls: Queue Testing v2.6

Status: Active testing reference
Updated: 2026-03-19

## 1. Purpose

StableNew fresh execution is queue-only.

Queue tests are intentionally asynchronous and must validate the real
queue-backed lifecycle rather than simulating a second execution path.

## 2. Canonical Driver Layer

Tests should drive through the real user-facing path:

GUI or controller -> `JobService` -> queue -> `PipelineRunner` -> history/result recording

Do not bypass this with direct runner driving unless the test is explicitly a
runner-unit test.

## 3. Common Pitfalls

### Pitfall: Treating `Run Now` as a direct execution mode

`Run Now` is queue submit plus immediate auto-start. Tests must not assume a
separate `DIRECT` runtime.

### Pitfall: Calling manual queue-driving hooks after queue submission

If the background runner is enabled, manual queue-driving calls create races and
false failures.

### Pitfall: Asserting against the original job object

Terminal status belongs to the stored queue/history record, not to a stale
pre-submission object reference.

### Pitfall: Using `sleep()` instead of polling

Polling terminal state is the correct pattern. Blind sleeping is flaky.

### Pitfall: Rebuilding status from logs instead of canonical history/results

Tests should assert against structured queue/history/result state whenever
possible.

## 4. Correct Test Patterns

Use:

- queue submission through the real controller or service seam under test
- polling against history or result state
- deterministic mocks for external runtimes
- explicit cleanup for local worker threads when test-owned services are created

Avoid:

- direct runner execution for fresh jobs
- mixed manual and background queue driving
- stale object assertions
- time-based sleeps as the primary synchronization method

## 5. Queue-Test Checklist

- submit work through the intended queue-facing seam
- wait for terminal state by polling
- assert terminal state from canonical history or stored result
- verify artifacts or summaries through canonical result metadata
- clean up locally started services, threads, or process managers

## 6. Notes

- Recovery, watchdog, and diagnostics behavior may emit additional logs without
  changing the required terminal queue outcome.
- Video workflow jobs follow the same queue-first testing rule as image jobs.
