Timestamp: 2025-11-22 20:15 (UTC-06)
PR Id: PR-#45-CONTROLLER-V2-QueueBackedRunIntegration-001
Spec Path: docs/pr_templates/PR-#45-CONTROLLER-V2-QueueBackedRunIntegration-001.md

# PR-#45-CONTROLLER-V2-QueueBackedRunIntegration-001: Finish Queue-Backed Run Integration (Completes PR-#40)

## What’s new

This PR completes the **queue-backed execution path** that was introduced conceptually in PR-#40 but not fully wired end-to-end. It:

- Wires **QueueExecutionController** into `PipelineController` so that the controller can:
  - Route **Run** requests through the job queue when a **queue_execution_enabled** flag is set.
  - Track an `active_job_id` rather than only a direct worker thread.
  - Receive job status callbacks and map them to **controller lifecycle** states.
  - Use queue-based cancellation when stopping a run.
- Exposes the **queue_execution_enabled** flag via configuration and surfaces it to GUI V2:
  - Configuration (for example, `app_config.py`) owns the default (OFF by default).
  - GUI V2 can read the flag and (optionally) show or use queue-mode semantics without changing the main user-facing Run flow by default.
- Extends/finishes tests:
  - Controller queue-mode toggle tests for `PipelineController`.
  - GUI V2 smoke tests to ensure the Run button respects queue mode.
  - Lifecycle mapping tests to ensure job status → controller lifecycle transitions behave as defined in Architecture v2.

This PR is **integration and wiring** only: it does not change queue core semantics, job model, or pipeline stage logic. It simply completes the queue-backed control flow from GUI → controller → queue → runner → callbacks → controller → GUI.

---

## Files touched

> Adjust exact module names to match your repo. Keep changes confined to controller, config, and GUI wiring; do not alter pipeline/core queue internals.

### Controller

- `src/controller/pipeline_controller.py`
  - Integrate **QueueExecutionController** explicitly:
    - Add a dependency injection path in the constructor or factory for:
      - `queue_execution_controller: QueueExecutionController | None`
    - Add a **queue execution flag** lookup:
      - Reads from app config or a controller-level setting:
        - `self._queue_execution_enabled: bool`
    - Update the **run** entrypoint (for example, `run_pipeline`, `run_full_pipeline`, or `start_run` depending on current naming) to:
      - Use the **existing direct execution path** when `queue_execution_enabled` is `False` (no behavioral change from current stable behavior).
      - Use the **queue-backed path** when `queue_execution_enabled` is `True`:
        1. Build a `PipelineConfig` (via the assembler from PR-#38; this PR assumes that path exists and will be fully enforced in PR-#46).
        2. Call `queue_execution_controller.submit_pipeline_job(config)` to obtain a `job_id: str`.
        3. Store `self._active_job_id = job_id`.
        4. Move controller lifecycle state to RUNNING (or RUNNING/QUEUED) per Architecture v2 rules.
    - Update the **stop/cancel** path (for example, `request_stop` / `stop_pipeline`):
      - When in queue mode and `active_job_id` is present:
        - Call `queue_execution_controller.cancel_job(self._active_job_id)`.
        - Transition controller state through STOPPING → IDLE (or straight to IDLE) according to existing rules.
      - When queue mode is disabled:
        - Preserve current direct-cancellation behavior.

  - Add a job-status callback handler (`on_job_status_changed`) if it doesn’t exist yet:
    - Signature: `on_job_status_changed(job_id: str, status: JobStatus) -> None`
    - Behavior:
      - If `job_id != self._active_job_id`:
        - Ignore or log a diagnostic and return.
      - Else:
        - Map job status to controller lifecycle:
          - JobStatus.QUEUED → controller state = RUNNING (with GUI text “Queued”, if available).
          - JobStatus.RUNNING → controller state = RUNNING.
          - JobStatus.COMPLETED → controller state = IDLE; fire “run completed” callbacks.
          - JobStatus.FAILED → controller state = ERROR; surface error state as appropriate.
          - JobStatus.CANCELLED → controller state = IDLE (or STOPPING→IDLE).
        - Clear `self._active_job_id` on terminal states (COMPLETED / FAILED / CANCELLED).

### Queue/controller integration

- `src/controller/queue_execution_controller.py`
  - Ensure there is a stable interface providing at least:
    - `submit_pipeline_job(config: PipelineConfig) -> str`
    - `cancel_job(job_id: str) -> None`
    - A callback registration or injection mechanism so that:
      - The PipelineController can receive job status changes:
        - For example, `register_status_callback(callback: Callable[[str, JobStatus], None])`.
  - No GUI imports, no direct Tk usage; remain in controller layer.

### Config

- `src/utils/app_config.py` (or equivalent)
  - Add a configuration flag:
    - `queue_execution_enabled: bool = False` (default).
  - Provide a clear getter/setter:
    - `def is_queue_execution_enabled(self) -> bool`
    - `def set_queue_execution_enabled(self, value: bool) -> None` (if you support runtime toggling).
  - Ensure this flag is loaded from your config file (toml/yaml/json) using existing patterns so it can be toggled per environment.

### GUI V2 wiring

- `src/gui/main_window.py`
  - Ensure the GUI reads the flag (via app config or controller):
    - For example, on initialization:
      - `queue_mode = app_config.is_queue_execution_enabled()`
  - When wiring up the Run button callback:
    - Keep the callback exactly the same from GUI’s perspective (for example, `self.controller.on_run_button_clicked()`).
    - The controller internals decide whether to use queue mode or direct mode based on the flag.
  - Optionally, add:
    - A simple status label or text update to show “Queued” when the controller or status panel tells GUI the job is queued (this can be minimal and piggyback on existing status panel code).

- `src/gui/app_layout_v2.py`
  - Only minimal changes, if any:
    - Ensure controllers are passed in with the new queue-mode configuration already applied.
    - No direct queue or job imports; remain layout-only.

### Docs

- `docs/ARCHITECTURE_v2_COMBINED.md`
  - Update **Controller** and **Queue** sections to clarify:
    - PipelineController owns the queue-mode toggle.
    - QueueExecutionController is the canonical bridge from controller to JobQueue/runner.
    - Job status → controller lifecycle mapping is now fully defined.

- `docs/PIPELINE_RULES.md`
  - Add a short section:
    - “Queue-Backed Execution Mode” describing:
      - When the mode is active (config flag).
      - That PipelineConfig is always used as the job payload.
      - That cancellation must go through queue semantics.

- `docs/codex_context/ROLLING_SUMMARY.md`
  - Updated as described below.

---

## Behavioral changes

- **Default behavior (queue_execution_enabled = False)**

  - No user-visible changes:
    - Run button triggers the same direct pipeline execution as before.
    - Cancellation uses existing direct CancelToken / worker-thread semantics.
  - Queue and QueueExecutionController may exist but are not used by default.

- **Queue mode ON (queue_execution_enabled = True)**

  - When enabled (for example, in advanced configs or during testing):
    - Run:
      - Submits a job via QueueExecutionController.
      - Sets `active_job_id`.
      - Reacts to job status events to drive controller lifecycle and GUI status.
    - Stop:
      - Cancels the active job via QueueExecutionController.
      - Ensures job status transitions to CANCELLED and controller returns to IDLE.
  - GUI can optionally show “Queued” before job starts running, if your status panel supports it.

- **Non-goals**

  - This PR does **not**:
    - Change queue ordering or job priorities.
    - Implement multi-worker scheduling or cluster behavior.
    - Add new GUI panels (that is covered by PR-#42 and later PRs).

---

## Risks / invariants

- **Invariants**

  - Controllers remain the **sole bridge** between GUI and queue:
    - GUI never imports `JobQueue` or `QueueExecutionController` directly.
  - Queue semantics remain:
    - Priority + FIFO as defined in PR-#35.
  - PipelineConfig remains:
    - The only payload for jobs; no ad-hoc config dicts are introduced.
  - Lifecycle:
    - Controller lifecycle states (IDLE, RUNNING, STOPPING, ERROR) must be updated only via the controller, not directly from queue or GUI.

- **Risks**

  - If job status callbacks are miswired:
    - Controller may remain stuck in RUNNING after completion or failure.
  - If queue cancellation doesn’t propagate properly:
    - Jobs might continue executing after user hits Stop.
  - If the queue_execution_enabled flag is accidentally set to True in non-ready environments:
    - Users might get unexpected queue behavior before it is fully validated.

- **Mitigations**

  - Keep job-status mapping logic small and unit-tested.
  - Default queue_execution_enabled to **False** and only enable it explicitly in config or tests.
  - Ensure callback wiring is deterministic:
    - Use a single callback registration path from QueueExecutionController → PipelineController.

---

## Tests

Run at minimum:

- **Controller tests**

  - `tests/controller/test_pipeline_controller_queue_mode.py -v`
    - Add scenarios:
      1. `queue_execution_enabled=False`:
         - Run uses direct path (no call to QueueExecutionController).
         - Controller lifecycle behavior unchanged.
      2. `queue_execution_enabled=True`:
         - Run:
           - Submits a job via QueueExecutionController.
           - Stores `active_job_id`.
         - Simulated callbacks:
           - QUEUED → controller RUNNING, optional “Queued” annotation.
           - RUNNING → controller RUNNING.
           - COMPLETED → controller IDLE, clears `active_job_id`.
           - FAILED → controller ERROR, clears `active_job_id`.
           - CANCELLED → controller IDLE (or STOPPING→IDLE), clears `active_job_id`.
      3. Stop:
         - In queue mode:
           - Calls `queue_execution_controller.cancel_job(active_job_id)` when active.
           - Does not call direct cancellation path.

- **Queue/controller integration**

  - `tests/controller/test_queue_execution_controller.py -v`
    - Extend as needed to:
      - Confirm callbacks are invoked with expected job_id and status for runners.
      - Confirm cancel_job triggers runner/queue cancellation.

- **GUI V2**

  - `tests/gui_v2/test_run_button_queue_mode_toggle.py -v`
    - Use a fake controller that:
      - Records when queue mode is active.
      - Records calls from the Run button.
    - Verify:
      - Run button always calls the same controller method.
      - Toggling queue_execution_enabled changes which internal path is used (direct vs queue-backed), not the GUI’s wiring.

- **Regression**

  - `pytest tests/controller -v`
  - `pytest tests/gui_v2 -v`
  - `pytest tests/queue -v`
  - `pytest -v`

Expected results:

- All new queue-mode tests pass.
- Existing tests remain green; no regressions in direct pipeline runs or GUI behavior.

---

## Migration / future work

With queue-backed run integration complete, future PRs can:

- Safely **enable queue mode by default** once it has enough mileage and diagnostics.
- Build:
  - GUI job panels (already covered in PR-#42 and PR-#43).
  - Cluster scheduling (PR-#44 and beyond).
  - Learning/rand-matrix batch runs via queued jobs instead of direct loops.

This PR is the “flip the wiring live” step that turns the queue from a background concept into a real execution path.

---

## Rolling summary update (for `docs/codex_context/ROLLING_SUMMARY.md`)

Append under the appropriate date (for example, `## 2025-11-22`):

- Completed the **queue-backed execution path** by wiring `QueueExecutionController` into `PipelineController` with a `queue_execution_enabled` feature flag, enabling Run/Stop to operate on queued jobs when enabled.
- Added job status → controller lifecycle mapping (QUEUED/RUNNING/COMPLETED/FAILED/CANCELLED), ensuring that queued runs drive the same lifecycle states and GUI updates as direct runs.
- Expanded controller and GUI V2 tests to validate queue-mode toggling, job-id tracking, and cancellation, without regressing default direct-execution behavior.
