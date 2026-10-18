# PR-RUNTIME-QUEUE-TRANSITION-ATOMICITY - atomic queue transitions and dispatch-certain Cancel and Return

Result class: **BOUNDED LIFECYCLE REPAIR** (execution class: Standard, with one owner-authorized behavior change to Cancel and
Return). No second queue, runner, history or cancellation authority; no durable `CANCELLING` status, schema change or NJR
rewrite. The canonical path is untouched:
`Intent -> Compiler -> NJR -> JobService -> SQLite Queue/Repository -> PipelineRunner.run_njr -> Handler/Executor -> Artifacts/History`.

**Model recommendation:** Claude Code Sonnet 5.5 XHigh; Codex GPT-6.1 Sol XHigh (difficult bounded concurrency/persistence work;
local host preferred because SQLite, threads and Windows lifecycle behavior affect validation).
**Controller Surface Assessment:** `JobService.cancel_current` only signals now; `src/controller/job_service.py` shrank and its
ceiling was lowered (no ceiling raised). The new logic lives in `src/queue/` (`dispatch_evidence.py`, `job_queue.py`).
**Token-Efficient Validation Plan:** reproductions first (on the base SHA), focused queue/service suites, the ratchets, then
`python tools/ci/run_pr_gate.py --full` once, then one independent verifier on the aggregate commit.

## Owner outcome

Queue/repository transitions have coherent commit semantics and a safe in-memory projection, and no generation request whose
dispatch outcome is unknown is replayed automatically. The SQLite row owns lifecycle state; the live job and the runnable heap
are projections of it. A RUNNING job returns to QUEUED under the same identity only on positive dispatch evidence.

## Defects found (all reproduced on unmodified source before any production change)

Real `JobRepository` (SQLite file) / `JobQueue` / `SingleNodeJobRunner` / `JobService`; interleavings are forced with events and a
repository seam around the commit (`tests/helpers/queue_choreography.py`), never with sleeps. On the base SHA the new reproduction
files fail 36 tests (7 guard tests pass); with the repair they all pass.

| Test (file) | Observed on the base SHA |
|---|---|
| `test_transition_job_does_not_mutate_the_job_it_is_given`, `test_a_failed_transaction_leaves_the_candidate_unchanged` (`test_transition_atomicity.py`) | `transition_job` zeroed the caller's progress/ETA, also when its own write then failed |
| `test_a_losing_return_leaves_the_live_job_untouched` | a return that lost its compare-and-transition had already edited the live job (`result` wiped, count raised) |
| `test_a_double_return_counts_once` | one return persisted `return_to_queue_count == 2` |
| `test_a_return_in_flight_is_not_overtaken` | the return held no lock while committing: a cancel then committed over it and the return's stale projection resurrected QUEUED on the cancelled job; a publish leaked `JobStatusChanged` to the runner |
| `test_progress_that_loses_the_race_with_a_return_is_not_resurrected` | a late report wrote 0.6 / ETA 9.0 onto the QUEUED row (live job said 0.0) |
| `test_metadata_written_during_a_transition_survives_the_projection` (pid / retry / checkpoint) | the projection replaced the live metadata with an older snapshot: SQLite had the update, the live job lost it (so the pid was never cleaned up) |
| `test_an_exception_after_a_successful_commit_...`, `test_a_projection_failure_after_commit_...` | live job RUNNING (or a COMPLETED job still projected) while the row said COMPLETED |
| `test_observers_see_committed_state_only_after_it_is_visible`, `..._may_re_enter_...` | the return paths announced QUEUED before the projection ran; a re-entrant claim got nothing |
| `test_cancelling_a_queued_job_through_the_execution_controller_...` | `Job.mark_status` edited the live job only; SQLite stayed QUEUED |
| `test_run_once_refuses_to_requeue_possibly_dispatched_work` (9 cases), `test_the_worker_loop_refuses_the_same_way` (`test_cancel_return_dispatch_certainty.py`) | every possibly dispatched job was put back in the queue, including one that had finished and produced output (generated twice by the continuous worker) |
| `test_cancel_current_with_return_...`, `test_a_runner_failure_...`, `test_a_plain_cancel_...` | `JobService.cancel_current` set `last_control_action` on the live job before anything committed; after a plain cancel the live job said `cancel_requested` and the row did not |

The old unit test that pinned the defect (`test_run_once_cancel_return_to_queue_requeues_job`: a job that had produced output was
requeued) now asserts the accepted policy. The other updated tests only pass the now-explicit evidence.

## Writers traced

| State | Writers | Coordination now |
|---|---|---|
| progress, ETA | `JobExecutionController._handle_runtime_status_update` (pipeline thread). The Tk running-job panel edits a `UnifiedJobSummary`, not a queue `Job`. | `JobQueue.record_progress`: under the queue lock, refused once the job is not RUNNING, SQL guarded on `status = 'running'`; transitions reset it in the candidate |
| result, error message, timestamps, worker id | transitions only (`publish_result`, `mark_*`, claim, returns) | candidate -> guarded commit -> projection |
| error envelope | the runner and the watchdog set it on the live job just before the transition that persists it (same thread, sequential); the refusal envelope is built in the candidate | unchanged / candidate |
| external pids, retry attempts | `JobService.register_external_process`, `record_retry_attempt`, `_pop_combined_metadata` (any thread, in place) then `persist_runtime_state` | `persist_runtime_state` runs under the queue lock; the projection merges metadata in place and never replaces these lists |
| stage checkpoints | the replay-engine checkpoint callback (pipeline thread, in place) then `persist_runtime_state`; `publish_result` (candidate) | same; checkpoints are adopted by the projection only when the transition published them |
| control action, return count | transitions only; `JobService` no longer touches them | candidate |

## Contract after the repair

* **Protocol.** Candidate (a private copy; metadata copied) -> the repository's guarded `transition_job` (the linearization point;
  it never writes to its argument and returns the committed row read in the same transaction) -> projection onto the live job and
  heap. All under `JobQueue._lock`, inside `defer_emissions()`, so observers run after the lock is released and after the
  projection is visible. Lock order: `_admission_lock` -> `_lock` -> the repository lock.
* **Failure after the commit point.** A projection failure, or a repository exception after COMMIT where the row shows the target
  status, is reconciled from the committed row (keeping the claim's heap counter); a commit is never reported as rolled back. A
  failure before the commit, a lost compare-and-transition, or an illegal edge changes nothing live.
* **Dispatch evidence** (`src/queue/dispatch_evidence.py`). One verdict for the outage requeue and for Cancel and Return:
  `FailureAssessment.safe_to_requeue`, reduced to "unsafe" by any recorded checkpoint or output. The queue re-checks it against
  the live job under its lock. An empty checkpoint list, a success result, an untyped failure, a timeout, an unclassified
  exception or a `CancellationError` are not evidence.

## Cancel and Return, as the operator sees it

* **Returned** (same identity, back of the queue): the worker never invoked the run callable for this claim (a stop request landed
  between the claim and the call), or the attempt's typed result/exception positively shows nothing was dispatched (ready-gate
  refusal, connection refused before dispatch) and no checkpoint or output was recorded.
* **Refused** in every other case, including a job with no completed stage checkpoints: the stop is honoured as a cancel. The job
  ends CANCELLED, never requeued, `return_to_queue_count` unchanged, `last_control_action = return_to_queue_refused_dispatch_uncertain`,
  with a `CANCEL_RETURN_REFUSED_DISPATCH_UNCERTAIN` error envelope (`action_required`, `generation_outcome: ambiguous`,
  `automatic_replay: false`, remediation: inspect outputs and backend state, then Replay Job only if a new run is intended).
  The existing job-failed event carries that envelope to `AppController`, which shows the message and remediation in the
  structured-error dialog and the last-error line; the persisted history entry keeps it. Re-running uncertain work is a
  deliberate Replay (a new NJR with lineage).

## Owner decisions and judgment calls

1. **Refused return ends CANCELLED, not FAILED.** The operator asked to stop, and a plain cancel of a possibly dispatched job
   was already CANCELLED. Consequence: only the job-failed event and the persisted envelope flag it; History still reads
   "Cancelled", Operator Readiness counts only `restart_interrupted_action_required`, and batch triage/Retry Selected Failed
   ignore CANCELLED rows. Making the unknown outcome durable in those views (a display tweak plus a readiness count) is a small,
   separate decision.
2. **`NEVER_INVOKED`** (the worker's proof that the callable was not called) is modelled as a `FailureAssessment`
   (`NOT_WEBUI`, `NOT_DISPATCHED`, `safe_to_requeue`) instead of a new evidence contract.
3. **A lost compare-and-transition does not reconcile the live projection** (it must leave it unchanged). Only an out-of-band
   writer that bypasses the queue can cause one.
4. **The offline legacy importer** (`src/migrations/sqlite_job_importer.py`) still maps a legacy `running` record to QUEUED
   (`legacy_running_requeued`), unlike live restart recovery (FAILED, action-required). It is an import, not a live transition,
   and was not changed; aligning it is a migration-contract decision.

## Residual risks and next package

* `src/pipeline/replay_engine.py` retries `run_njr` without the checkpoint callback on any `TypeError`; a `TypeError` raised after
  a stage dispatched would re-invoke the runner. Pre-existing, outside the queue, and the next place a "never replay an
  ambiguous dispatch" audit should look.
* The operator-return heap position (back of the queue) is not durable: after a restart the job reappears at its durable
  `queue_order`.
* `JobExecutionController.cancel_job` is reachable only through `PipelineController.stop_pipeline`, which needs an
  `_active_job_id` that nothing assigns today; it is guarded now regardless.
* A pre-existing unhandled-thread warning from a test double (`ControlledAsyncRunner` in
  `tests/controller/test_core_run_path_v2.py` completing a QUEUED job) surfaces on a neighboring test; it reproduces on the base
  SHA and is unrelated.
* Readiness for the WebUI containment contract: the lifecycle it needs (guarded transitions, a single dispatch-evidence verdict,
  an operator-action-required result for uncertain work, three-way agreement checks in `queue_choreography`) is in place; the
  open WebUI manager questions (best-effort attach, uncontained trainer) are unchanged and still need their owner decisions.

## Validation

`tests/queue/test_transition_atomicity.py`, `test_cancel_return_dispatch_certainty.py`, `test_return_evidence_gate.py` (including
source-level guards that fail if a transition path assigns to a live job ahead of its commit), the existing queue/outage/service
suites, `python tools/ci/run_pr_gate.py --full`, and one independent verification pass whose confirmed in-scope findings
(two untested lock acquisitions, a lost claim counter and a checkpoint race in the reconcile, an over-broad refusal wording)
were repaired (the two lock tests were mutation-checked: removing either lock turns them red) and the gate re-run. The verifier
reported no blocking defect, so no second independent pass was needed.
