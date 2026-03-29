# PR-QUEUE-067: Queue Lifecycle Semantics and Checkpoint Recording

## Summary

Normalize the live queue control contract so the queue, runner, job service, and
controller surfaces agree on:

- queue pause / resume
- cancel current job
- cancel current job and return it to the queue
- lightweight checkpoint metadata recording for completed stage sequences

This PR does not implement full resume-from-checkpoint execution. It records the
checkpoint substrate and removes the current control-path drift first.

## Problem

The current queue surface has three mismatches:

1. Controllers call `queue.pause()`, `queue.resume()`, `queue.pause_running_job()`,
   `queue.resume_running_job()`, and `queue.cancel_running_job(...)`, but
   `JobQueue` does not implement those methods.
2. `cancel_current()` and "cancel and return" semantics are split across
   controller, job service, queue, and runner, which risks duplicate state
   transitions and stale completion writes.
3. `JobExecutionMetadata` only captures retry attempts and external PIDs. It does
   not record any checkpoint-like summary from canonical run results, so later
   resume work has no queue-side substrate.

## Goals

1. Make pause/resume a real queue contract on `JobQueue`.
2. Make cancel-and-return a real runner-aware contract instead of a controller
   side mutation.
3. Ensure a late cancel request cannot silently overwrite queue intent with a
   completed status if the runner returns after cancellation was requested.
4. Record lightweight checkpoint metadata from canonical run results without
   changing queue/history persistence schemas.
5. Keep queue/job execution architecture unchanged.

## Non-Goals

1. No full resume-from-checkpoint execution.
2. No queue persistence schema migration.
3. No history schema changes.
4. No GUI redesign.

## Allowed Files

- `src/queue/job_model.py`
- `src/queue/job_queue.py`
- `src/queue/single_node_runner.py`
- `src/controller/job_service.py`
- `src/controller/app_controller.py`
- `src/controller/pipeline_controller.py`
- `tests/queue/test_job_queue_basic.py`
- `tests/queue/test_jobrunner_integration.py`
- `tests/controller/test_job_service_unit.py`
- `tests/controller/test_job_service_process_cleanup.py`
- `tests/controller/test_job_queue_integration_v2.py`
- `docs/PR_MAR26/PR-QUEUE-067-Queue-Lifecycle-Semantics-and-Checkpoint-Recording.md`

## Forbidden Files

- `src/pipeline/pipeline_runner.py`
- `src/pipeline/executor.py`
- `src/history/`
- `src/gui/`
- canonical architecture docs outside this PR record

## Implementation

### 1. Queue lifecycle methods

Add explicit queue state methods to `JobQueue`:

- `pause()`
- `resume()`
- `is_paused()`
- `pause_running_job()`
- `resume_running_job()`
- `cancel_running_job(return_to_queue=False)`

Semantics:

- queue pause stops future dequeues; it does not promise true mid-stage
  suspension of an already-running pipeline call.
- `pause_running_job()` / `resume_running_job()` are graceful aliases around the
  queue-level pause contract so controller calls stop drifting.
- `cancel_running_job(return_to_queue=True)` requeues the running job at the back
  of the queue with cleaned transient state.

### 2. Runner-aware cancel-and-return

Update `SingleNodeJobRunner` so `cancel_current(return_to_queue=False)` stores the
intent and checks it both:

- before invoking the job callable
- after the callable returns but before it writes final completed/failed state

That prevents a late cancel request from being overwritten by a successful run
return when the underlying pipeline stops cooperatively near the end.

### 3. Job service normalization

Update `JobService` so:

- `pause()` / `resume()` call through to `JobQueue`
- `cancel_current(return_to_queue=True)` uses the runner-aware contract instead
  of controller-side direct queue mutation
- queue status events remain `paused` / `running` / `idle`

### 4. Lightweight checkpoint metadata

Extend `JobExecutionMetadata` with a bounded checkpoint summary derived from
canonical run results:

- completed stage names
- final output paths seen in the canonical result
- checkpoint timestamp

This data is runtime-only and is not yet used for resume execution.

### 5. Controller cleanup

Update `AppController` and `PipelineController` to use the normalized
`job_service.cancel_current(return_to_queue=True)` path and stop mutating queue
state directly for the return-to-queue case.

## Test Plan

- `tests/queue/test_job_queue_basic.py`
  - queue pause/resume semantics
  - cancel-running-job return-to-queue behavior
- `tests/queue/test_jobrunner_integration.py`
  - paused queue blocks dequeue until resume
  - cancel-and-return preserves queued job for retry
- `tests/controller/test_job_service_unit.py`
  - pause/resume delegate to queue
  - cancel current with `return_to_queue=True` uses the normalized path
- `tests/controller/test_job_service_process_cleanup.py`
  - cancel current still finds running job and preserves current cleanup behavior
- `tests/controller/test_job_queue_integration_v2.py`
  - controller queue controls continue to update UI state correctly

## Verification

- `pytest tests/queue/test_job_queue_basic.py tests/queue/test_jobrunner_integration.py tests/controller/test_job_service_unit.py tests/controller/test_job_service_process_cleanup.py tests/controller/test_job_queue_integration_v2.py -q`
- `pytest --collect-only -q`
- `python -m compileall src/queue/job_model.py src/queue/job_queue.py src/queue/single_node_runner.py src/controller/job_service.py src/controller/app_controller.py src/controller/pipeline_controller.py tests/queue/test_job_queue_basic.py tests/queue/test_jobrunner_integration.py tests/controller/test_job_service_unit.py tests/controller/test_job_service_process_cleanup.py tests/controller/test_job_queue_integration_v2.py`
