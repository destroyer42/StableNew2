# PR-RUNTIME-SHUTDOWN-140 - Shutdown admission fence and repository quiescence

Result class: **BOUNDED LIFECYCLE REPAIR**. No queue redesign, startup-policy change, schema change or runtime change. The
canonical path is untouched:
`Intent -> Compiler -> NJR -> JobService -> SQLite Queue/Repository -> PipelineRunner.run_njr -> Handler/Executor -> Artifacts/History`.
Execution Profile: difficult bounded lifecycle/persistence/concurrency (Claude Code: Sonnet 5.5 XHigh).

## Owner outcome

Once application shutdown begins, no additional queued job can acquire RUNNING ownership, and the shared SQLite
`JobRepository` is not closed until every queue worker capable of touching it has definitively quiesced. Already-QUEUED jobs
still survive shutdown and resume under the existing startup auto-run policy.

## Verified root cause

A real shutdown with an active image job and a persisted queued job showed: shutdown began, the active generation was
cancelled and runtime teardown started, the next QUEUED job was then claimed RUNNING, shutdown later closed the shared
repository, and the unwinding worker failed with `sqlite3.ProgrammingError: Cannot operate on a closed database`. Four source
mechanisms made that possible, all reproduced on unmodified source:

1. `AppController.shutdown_app` cancelled the active job first but only stopped the queue at step 5; between the two,
   `SingleNodeJobRunner` (auto-run still on, `_stop_event` still clear) handed off to the next job as soon as the cancelled
   one unwound.
2. `_worker_loop` checked dispatch permission under `_lifecycle_lock`, released it, and only then called
   `JobQueue.claim_next_job()`: the permission check and the claim were not atomic with any stop/fence transition.
3. `SingleNodeJobRunner.stop()` set an event and joined for 10 s but returned nothing, and `JobService._stop_runner` skipped
   stopping entirely when it had not marked a continuous worker started (a Run Now one-shot worker).
4. `AppController.shutdown()` closed the repository unconditionally, whatever the worker was doing.

## Pre-fix reproductions (kept as permanent regression tests)

Real temporary `JobRepository`/`JobQueue`/`JobService`/`SingleNodeJobRunner` and real threads; only the job callable is
fake; synchronization is `threading.Event`/`Barrier` (no sleeps as synchronization).

* `tests/queue/test_shutdown_admission_fence_140.py`: the worker pinned between the permission check and the claim while
  shutdown fences (B acquired RUNNING after shutdown began); the cancellation unwind claiming B; the Run Now handoff pinned
  before `mark_running`; submissions, resume and Run Now after the fence; non-quiescing worker; pending jobs surviving a restart.
* `tests/controller/test_shutdown_quiescence_140.py`: the real `AppController.shutdown_app` over a real stack: B started after
  shutdown began, no fence recorded before cancel/WebUI teardown, and SQLite closed under a live worker, which raised the
  production `ProgrammingError` in the worker's `mark_failed`. Idle and repeated shutdown stay safe.

## Contract after the repair

**Admission fence.** `JobQueue.fence_dispatch()` sets a process-lifetime flag under the same lock that makes
`claim_next_job` (and the one-shot `mark_running`) atomic with their durable SQLite transition. A claim either completed
before the fence returned or sees it: there is no check-then-claim window. A fenced queue returns no claim, refuses a QUEUED
-> RUNNING transition, and leaves every job durably QUEUED. It is not persisted (a restarted queue is unfenced, so recovery
and the startup auto-run policy are unchanged), it is not the pause setting, and `JobService.auto_run_enabled` is never
read or changed. The job that already owns RUNNING can still publish its result, be cancelled, or be returned to the queue.

**Runner.** `SingleNodeJobRunner.begin_shutdown()` fences the queue, then makes `start()`/`run_next_once()` inert, stops
the one-shot -> continuous handoff and retires the worker loop after the job it already owns. It is lock-free on purpose:
a worker holds `_lifecycle_lock` while it evaluates the dispatch policy, which must never delay shutdown. The runner tracks
every worker thread it launched; `is_quiescent()` is true only when none is alive, and `stop(timeout=10.0)` returns that
result (a join that merely returned is not quiescence).

**JobService.** `begin_shutdown()` (terminal, idempotent), `is_quiescent()` and `stop(timeout=None) -> bool` live in
`src/controller/job_service_shutdown.py` (the existing `job_service_auto_run`/`job_service_dispatch` pattern, so the ratcheted
`job_service.py` shrank). `stop()` now also stops a live one-shot worker, and Run Now after the fence returns `False`.

**AppController (coordination only).** `src/controller/app_controller_services/shutdown_coordinator.py` sequences the owners:

1. shutdown becomes authoritative -> `fence_queue_admission` (before anything slow);
2. cancel the active job (unchanged semantics: backend interrupt, cancellation classification, ambiguous-POST handling and
   WebUI retry policy are untouched; an ambiguously dispatched generation POST is never replayed);
3. normal background/runtime teardown (an external WebUI/Forge/Comfy is never stopped or adopted);
4. `quiesce_job_service`: bounded stop (`QUEUE_QUIESCE_TIMEOUT_SECONDS`, 10 s) with a verified result;
5. final queue-state save while the repository is still open;
6. `close_repository_when_quiescent`: closes only when quiescent (a short final check covers a direct `shutdown()` call).

If the worker cannot quiesce (a backend that ignores cancellation), shutdown continues honestly: an ERROR names the abnormal
condition, no "Job repository closed" success line is logged, SQLite is **not** closed under the worker, and the queued
backlog stays durable. The existing shutdown watchdog and opt-in hard-exit are unchanged.

## Not changed / limits

* Startup queue policy, automatic resume on launch, pause-by-default, schema, NJR, backend/model/runtime selection: unchanged.
* A job that is already RUNNING and ignores cancellation still holds the worker until the bounded wait expires; the process
  then exits without closing SQLite (a persisted RUNNING row follows the existing interrupted-job recovery policy).
* `AppController.stop_all_background_work` still does not stop the queue by itself; shutdown relies on the fence taken at the
  start of `shutdown_app`.
* The quiescence set is the queue runner's worker threads (the only threads that call queue/repository lifecycle methods).

## Controller surface

`app_controller.py` shrank 7730 -> 7714 physical lines and `job_service.py` 1245 -> 1237; both ratchet ceilings were lowered.
No ceiling increased.

## Validation

Focused: `tests/queue/test_shutdown_admission_fence_140.py`, `tests/queue/test_dispatch_fence_unit_140.py` (including a
concurrent-claimer property that fails when the atomic fence is removed), `tests/controller/test_shutdown_quiescence_140.py`,
`tests/controller/test_shutdown_coordinator_140.py`, plus the existing queue lifecycle, auto-run worker, controller shutdown,
recovery and cancellation suites. No generation, GPU or external runtime was used.
