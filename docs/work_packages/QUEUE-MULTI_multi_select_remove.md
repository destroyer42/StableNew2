# QUEUE-MULTI: multi-select Remove and a fast, off-thread Clear All

Status: implemented on `claude/queue-multi` (2026-11-28), awaiting owner review and publish.

Owner request (2026-11-28): "allow multi select removal in the queue. Today only single and cancel all are options.
Removing all from the queue is a super slow expensive option (visibly hangs)." The owner queues prompt packs of
1,000 to 2,000 jobs and walks away.

Canonical path, unchanged: `Intent -> Compiler -> NJR -> JobService -> Queue/Repository -> PipelineRunner.run_njr ->
Handler -> Artifacts/History`. `JobQueue` stays the only queue authority and `JobRepository` the only persistence. No
second queue, runner or history path was added.

## 1. Diagnosis (measured)

Test: 2,000 QUEUED plain NJRs admitted through `JobService.submit_njrs` into a temporary SQLite repository, then
`JobQueue.clear()` on the calling (main) thread. `cProfile` for the split. Same machine, same interpreter.

| Measure | Before | After |
|---|---|---|
| `clear()` wall time, 2,000 jobs | 7.97 s | 0.70 s |
| Repository COMMITs | 2,000 | 1 |
| Queue-wide summary builds (`_format_queue_job_summary` calls) | 1,999,000 | 1 (one summary, after the batch) |
| State-listener notifications | 1 (already coalesced) | 1 |
| Heap rebuilds (`_prune_job`) | 2,000 | 1 |
| Thread | caller (the Tk thread, from `on_queue_clear_v2`) | tracked worker |

Where the 7.97 s went (profiled run, 17.4 s with profiler overhead, shares are what matter):

- About 57 percent in `JobService._handle_job_status_change`, one call per cancelled job. Each one called
  `_emit_queue_updated`, which formats a summary line for every job in the queue: 2,000 x 2,000 = 1,999,000 calls of
  `_format_queue_job_summary`. That is quadratic and was the largest cost. Each call also scanned the whole queue for
  "any QUEUED job left" to decide `EVENT_QUEUE_EMPTY`.
- About 30 percent in the per-job repository commit (`sqlite3 commit` 4.9 s of 17.4 s): 2,000 separate transactions.
- The rest was per-job heap pruning (rebuild plus heapify of the whole heap each time) and snapshot decoding.

`clear()` already used `coalesce_state_notifications()`, so listeners were not the problem; the per-job job-service
handler and the per-job transaction were. On the live app all of this ran on the Tk thread, which is the visible hang.

## 2. Design

- `JobRepository.transition_jobs(jobs, status, ...)`: one transaction, one COMMIT. Each row goes through the same
  guarded UPDATE as `transition_job` (the body moved unchanged into `_apply_transition`, which both use), so rows and
  history entries are identical to single transitions. A row the guard refuses is returned as its exception and
  nothing is written for it; any other failure rolls the whole batch back.
- `JobQueue.remove_many(job_ids, reason)` returns `RemoveManyOutcome(removed, running, missing, errors)`. Per removed
  job the record is what `remove()` gives: status CANCELLED, `error_message` = reason, repository history entry, the
  status callback (job events and completion handlers are kept), finalized-job bookkeeping, heap cleanup (one pass,
  `_prune_jobs`). One coalesced state notification. RUNNING jobs are never touched and are reported in `running`; the
  durable status is re-checked inside the transaction (`expected_status`), so a job the worker claims after the
  decision is reported as `running`, not cancelled.
- `JobQueue.clear()` is `remove_many` of every QUEUED job with reason `queue cleared`.
- `JobService._handle_job_status_change` no longer builds the queue summary per job while the queue is inside a
  coalesced batch: it marks the update as owed and a state listener publishes one `EVENT_QUEUE_UPDATED` (and the
  empty check) when the batch closes. This also speeds up `cancel_queued_jobs` (Cancel Remaining).
  `job_service_queue_batch.remove_queued_jobs(service, job_ids | None, reason)` is the service-level entry (`None` = every queued job); it lives in a new module because `job_service.py` and `app_controller.py` are under line-count ceilings.
- `AppController.on_queue_remove_jobs_v2(job_ids | None, *, reason, on_done)` (a 4-line shim over `app_controller_services/queue_removal.py`) submits the removal to the existing
  `BackgroundTaskCoordinator` (tracked thread registry, delivery through `_ui_dispatch`), one unique key per request so
  two requests never supersede each other. `on_done` runs on the UI thread with the outcome, or `None` on failure.
  Returns False when no worker could start (no service, or shutdown), so the panel never waits forever. The queue
  projection refresh and `_save_queue_state` run on the UI thread after the batch. The projection refresh was already
  a latest-wins background task.
- `QueuePanelV2`: `selectmode=EXTENDED` (Shift-click, Ctrl-click, Ctrl+A). "Remove" becomes "Remove selected (N)" for
  a multi-selection (N is the number of queued rows in it). Reorder buttons need exactly one selected row. Running
  rows in a selection are skipped, with a note in the result message. While a removal runs the Remove and Clear All
  buttons are disabled and the status line shows "Removing N jobs..."; the result message is "Removed N jobs; M running
  (must be cancelled)" (plus "already gone" and "failed" counts when they are non-zero). A multi-selection now
  survives list refreshes instead of collapsing to one row. A single queued row still uses the existing synchronous
  Remove (one row is cheap). Clear All always goes through the worker when the controller offers it.

## 3. Phone

Checked, no change needed. The phone queue view (`src/app/site_phone_queue.py`) reads job rows from the repository
(`read_phone_job_page`) and projects the stored status; nothing pushes phone items into a separate store that a
removal would have to withdraw from. A removed job is a CANCELLED row, exactly as with single Remove and Cancel
Remaining, so the phone shows it as cancelled. If the owner wants removed phone jobs to disappear from the phone list
instead of showing as cancelled, that is a separate display decision.

## 4. Tests

- `tests/queue/test_queue_remove_many.py`: semantics (only requested jobs, same row as single remove, running skipped,
  claim race, one commit and one notification, rollback on failure, restart, service `None`, one queue-updated event)
  and `clear()` of 2,000 jobs under 2 s.
- `tests/gui_v2/test_queue_multi_select_remove.py`: selection mode, label and button states, worker call with only
  queued ids, disabled while running, result messages, failure and could-not-start paths, selection survives refresh,
  and the controller worker path (does not block Tk, runs off the Tk thread, reports on it).
- `tests/gui_v2/test_pr_mvp_080_action_state_truth.py`: one line added, because `selection_set` now adds to a
  multi-select list instead of replacing the selection.

## 5. Not done

- No live-app acceptance. The owner has to try it with a real 1,000 to 2,000 job pack.
- The 0.70 s that remains is mostly per-job status callbacks (job events, completion handlers, job view) and snapshot
  decoding of each committed row; it is off the Tk thread now. Cancel Remaining (`cancel_queued_jobs`) still commits
  per job and could use `remove_many` later, but its guard semantics differ and it was left alone.
- `PipelineController.on_queue_clear_v2` still calls `queue.clear()` directly; it is fast now but is not off-thread.
  The AppController refactor (`CODE-HEALTH_appcontroller_executor_review.md`, slice 3) is the place to give the queue
  buttons one owner.

## 6. Ceiling note

The controller-surface ratchet allows no growth in `app_controller.py` and `job_service.py`. The logic went to new
modules (`job_service_queue_batch.py`, `app_controller_services/queue_removal.py`). `job_service.py` is net zero lines.
`app_controller.py` grew by 5 and shrank by 17 with the removal of `_run_pipeline_via_runner_only`: it had no caller in
`src/`, `tests/` or `tools/` and only ever raised (CODE-HEALTH review section 3, A11, verified dead). The ceiling in
`tools/ci/controller_surface_baseline.json` moved from 4749 to 4739.
