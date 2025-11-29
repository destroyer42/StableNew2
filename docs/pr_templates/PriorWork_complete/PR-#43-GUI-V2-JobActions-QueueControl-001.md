Timestamp: {timestamp}
PR Id: PR-#43-GUI-V2-JobActions-QueueControl-001
Spec Path: docs/pr_templates/PR-#43-GUI-V2-JobActions-QueueControl-001.md

# PR-#43-GUI-V2-JobActions-QueueControl-001: GUI V2 Job Actions (Cancel/Retry) via Controller Queue APIs

## What’s new

- Extends the **Job History & Active Queue panel** (from PR-#42) with **safe, controller-mediated job actions**:
  - **Cancel** a running or queued job from the GUI.
  - **Retry** a failed or completed job by submitting a new `PipelineConfig`-equivalent job.
- Introduces controller-level APIs to support these actions without violating architecture boundaries:
  - `cancel_job(job_id: str)`
  - `retry_job(job_id: str) -> str` (returns new job_id)
- Wires these actions into GUI V2 as:
  - Row-level buttons or a context menu in the Jobs panel.
  - Optional toolbar buttons (Cancel, Retry) that operate on the selected job.
- Adds tests that:
  - Verify GUI calls the correct controller methods.
  - Ensure controller maps actions to QueueExecutionController + JobHistoryService correctly.
- Updates docs & rolling summary so Codex knows GUI job actions must always flow via controller and never directly manipulate queue/history internals.

This PR is **GUI + controller integration** only. It does not change JobQueue’s core semantics, job history structure, or pipeline execution logic.

---

## Files touched

> Adjust exact filenames to your repo; keep responsibilities clearly separated.

### Controller

- `src/controller/job_history_service.py`
  - Adds high-level job actions:
    - `cancel_job(job_id: str) -> None`
      - Delegates to `QueueExecutionController` (or equivalent) to:
        - Cancel an active or queued job.
      - Updates history via existing callback flows (no direct writes here, if possible).
    - `retry_job(job_id: str) -> str`
      - Looks up `JobHistoryEntry` by id.
      - Retrieves or reconstructs the original `PipelineConfig`:
        - Uses a stored config reference if available, or
        - Uses a stored config snapshot, or
        - Uses a minimal descriptor with enough info for a controller-level “rebuild config” helper.
      - Submits a new job via `QueueExecutionController`.
      - Returns the new job id.
  - Enforces rules:
    - Only allow retry for jobs whose status is COMPLETED, FAILED, or CANCELLED.
    - Only allow cancel for jobs whose status is QUEUED or RUNNING.

- `src/controller/queue_execution_controller.py`
  - Exposes:
    - `cancel_job(job_id: str)` (if not already present).
    - An internal helper to support retry:
      - `submit_pipeline_job(config: PipelineConfig)` is already present from PR-#40; `retry_job` will call into this.
  - Does **not** implement GUI logic; stays job/queue-oriented.

### GUI V2

- `src/gui/job_history_panel_v2.py`
  - Extends the panel from PR-#42 with:
    - Job selection support:
      - Single selection (for example, clicking a row).
    - Actions:
      - **Cancel**:
        - Enabled when the selected job is QUEUED or RUNNING.
        - Calls `job_history_service.cancel_job(selected_job_id)`.
        - On success:
          - Optionally triggers a refresh.
      - **Retry**:
        - Enabled when the selected job is COMPLETED, FAILED, or CANCELLED.
        - Calls `job_history_service.retry_job(selected_job_id)`.
        - Optionally triggers a refresh and/or displays a message with the new job id.
    - UI elements:
      - Buttons in a small toolbar (for example, “Cancel Job”, “Retry Job”).
      - Or a context menu triggered on row right-click.

  - Must:
    - Remain Tk/Ttk-only.
    - Not import queue, job history, or pipeline modules directly.

- `src/gui/app_layout_v2.py`
  - Minimal updates to:
    - Ensure the Jobs panel’s new buttons/actions are visible.
    - No changes to other panels.

### Config / safety

- `src/utils/app_config.py` (or relevant config)
  - Optionally introduces a feature flag to:
    - Enable/disable GUI job actions (for example, `job_actions_enabled: bool = True`).
  - Useful if you want to restrict job actions in some environments.

### Docs

- `docs/ARCHITECTURE_v2_COMBINED.md`
  - Clarify:
    - GUI interacts with jobs only via controller’s job history / queue APIs.
    - Controllers mediate all cancel/retry semantics.
  - Note:
    - Cancel semantics:
      - Translate to queue/job cancellation.
    - Retry semantics:
      - Create new jobs; they do **not** resurrect old jobs.

- `docs/Cluster_Compute_Vision_v2.md`
  - In the queue/UX section:
    - Mention GUI job actions as a first step toward interactive control over local or future cluster jobs.

- `docs/codex_context/ROLLING_SUMMARY.md`
  - Add the summary bullets noted below.

---

## Behavioral changes

- For users:
  - The Jobs/Queue panel gains:
    - A **Cancel** control for in-flight jobs.
    - A **Retry** control for finished/failed jobs.
  - Typical flows:
    - If a job is stuck or unnecessary:
      - Select it, click Cancel; status transitions to CANCELLED, future work on that job stops.
    - If a job failed or produced unsatisfactory results:
      - Select it, click Retry; a new job is queued with the same core configuration.

- For the system:
  - Cancel:
    - Signals the queue/controller stack to cancel the job.
    - Must eventually propagate through:
      - QueueExecutionController → JobQueue/runner → CancelToken → PipelineRunner.
    - JobHistoryStore records the transition to CANCELLED.
  - Retry:
    - Creates a new job with:
      - Equivalent `PipelineConfig` (per your config capture design).
      - New job id and new timestamps.
    - Does not modify the original job entry; history remains immutable for previous jobs.

---

## Risks / invariants

- **Invariants**
  - GUI must never:
    - Cancel jobs directly at queue level.
    - Modify job history entries directly.
  - Controller must:
    - Enforce status checks (no retrying jobs that are still RUNNING or QUEUED).
    - Handle invalid job ids gracefully (for example, show error/status update instead of crashing).
  - JobHistoryStore remains append-only for status changes; retries produce new jobs.

- **Risks**
  - If retry config reconstruction is incorrect:
    - Retried jobs may behave differently than the original.
  - If cancel semantics aren’t fully respected by queue/runner:
    - Jobs may continue executing after being marked CANCELLED, leading to confusing UX.
  - Over-aggressive polling or frequent refreshes could:
    - Cause performance issues if JobHistoryService is not efficient.

- **Mitigations**
  - Start with:
    - A simple config capture for retry:
      - Store a serialized, sanitized `PipelineConfig` snapshot with each job history record.
    - Conservative refresh strategy in GUI:
      - Manual refresh only; no auto-refresh loops in this PR.
  - Add tests around:
    - Cancel behavior on allowed/forbidden statuses.
    - Retry behavior and config equality.

---

## Tests

Run at minimum:

- Controller:
  - `pytest tests/controller/test_job_history_service.py -v`
    - Add tests for:
      - `cancel_job` only allowed on QUEUED or RUNNING jobs.
      - `retry_job` creates a new job id and calls QueueExecutionController with expected config.
  - `pytest tests/controller/test_queue_execution_controller.py -v`
    - Add or extend tests to ensure:
      - `cancel_job` signals runner/queue correctly.

- GUI:
  - `pytest tests/gui_v2/test_job_history_panel_v2.py -v`
    - Add tests for:
      - Cancel button enabled/disabled by status.
      - Retry button enabled/disabled by status.
      - Correct controller calls made when actions are triggered.

- Regression:
  - `pytest tests/gui_v2 -v`
  - `pytest tests/controller -v`
  - `pytest tests/queue -v`
  - `pytest -v`

Expected results:

- New tests validate:
  - GUI → controller actions.
  - Controller → queue/history behavior.
- No regressions in queue semantics, job history persistence, or GUI V2 layout.

---

## Migration / future work

With GUI job actions in place:

- Future PRs can:
  - Implement:
    - “Retry with tweaks” (for example, modify specific parameters before resubmitting).
    - Bulk actions (cancel all queued jobs).
  - Extend job actions to:
    - Cluster nodes (for example, cancel jobs on a specific worker).
  - Introduce:
    - Fine-grained permissions for job actions (for example, only some users can cancel).

- Additionally:
  - Job-level logging or detail view PRs can build on top of this, allowing:
    - Deep inspection of failed jobs before retrying.

---

## Rolling summary update (for `docs/codex_context/ROLLING_SUMMARY.md`)

Append under the appropriate date (for example, `## 2025-11-22`):

- Extended the GUI V2 Jobs/Queue panel with **Cancel** and **Retry** actions wired through controller-level job history and queue APIs.
- Ensured that all job actions flow through controller facades (`JobHistoryService` and `QueueExecutionController`), preserving queue and history layering and keeping JobQueue semantics intact.
- Added tests to validate action availability by status and confirm that job cancellations and retries are correctly propagated from GUI → controller → queue/runner/history.
