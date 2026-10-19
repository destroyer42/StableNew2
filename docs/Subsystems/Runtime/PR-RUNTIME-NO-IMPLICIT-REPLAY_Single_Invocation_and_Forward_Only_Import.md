# PR-RUNTIME-NO-IMPLICIT-REPLAY: single invocation and forward-only import

Contract: a generation with an uncertain prior execution outcome never runs again implicitly under the same identity.
Living truth is `QUEUE_AND_RUNTIME.md` (invariant 15); this record is the evidence for the change.

## What changed

1. **`ReplayEngine.replay_njr`** (`src/pipeline/replay_engine.py`) used to call `run_njr(..., checkpoint_callback=...)` and, on
   any `TypeError`, call it again without the callback. A `TypeError` raised from inside execution (after backend dispatch)
   therefore dispatched the same job twice. Now `resolve_run_njr_kwargs` binds the intended call to the runner's
   `inspect.signature` *before* invoking it: the checkpoint callback is passed only if the signature accepts it (otherwise one
   call without it, with a warning), and a runner whose signature is uninspectable or cannot accept
   `(record, cancel_token, run_plan=...)` raises `RunnerCompatibilityError` without being called. There is exactly one
   `run_njr` call site; nothing catches an exception to call it again. The `execute_job` adapter in
   `JobExecutionController` uses the same resolution. Queue/JobService behavior is unchanged: a failed invocation publishes
   FAILED once (see `SingleNodeJobRunner._run_job_callable`).
2. **`sqlite_job_importer`** mapped legacy `running` to QUEUED and incremented `return_to_queue_count`. Future imports now map it
   to FAILED with the `INTERRUPTED_RESTART_ACTION_REQUIRED` envelope used by `JobRepository.recover_interrupted_jobs`
   (`generation_outcome: ambiguous`, `automatic_replay: false`, `legacy_original_status: running`), keep the prior legacy
   envelope/message in the context, set `last_control_action = restart_interrupted_action_required`, and leave the requeue count
   as imported. Identity, NJR, result, artifacts, checkpoints and timestamps are preserved. Dry-run now counts it terminal. Other
   statuses are unchanged. No schema change, no new status, no backfill of already-imported rows.

## Behavior notes

* An operator re-runs an imported interrupted job only through the normal Replay path (new identity, parent lineage).
* `completed_at` of an imported interrupted job is the legacy `updated_at` (existing importer rule for terminal jobs).
* A runner whose `run_njr` rejects `checkpoint_callback` still runs once, without checkpoint persistence (as before, minus the retry).

## Tests

`tests/pipeline/test_replay_engine_single_invocation.py`, `tests/migrations/test_sqlite_job_importer_running.py`.
