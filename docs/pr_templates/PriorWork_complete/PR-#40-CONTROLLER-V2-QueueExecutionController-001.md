Timestamp: 2025-11-22 19:12 (UTC-06)
PR Id: PR-#40-CONTROLLER-V2-QueueExecutionController-001
Spec Path: docs/pr_templates/PR-#40-CONTROLLER-V2-QueueExecutionController-001.md

# PR-#40-CONTROLLER-V2-QueueExecutionController-001: QueueExecutionController, Controller-Level Queue Plumbing, and GUI Job Lifecycle Wiring

## What’s new

- Introduces a dedicated **QueueExecutionController** in the controller layer to formalize the bridge between the **JobQueue / SingleNodeJobRunner** (PR-#35 / PR-#36) and the rest of the controller/GUI stack.
- Adds **controller-level queue plumbing**:
  - Enqueue: submitting `PipelineConfig` payloads as jobs.
  - Status: querying job status and exposing it in a controller-friendly form.
  - Cancellation: canceling jobs via the queue interface instead of raw thread cancellation.
- Wires the **StableNewGUI V2 “Run” pathway** (behind a feature flag) to optionally submit a Job into the queue, rather than invoking a direct run:
  - When the feature flag is ON, GUI → PipelineController → QueueExecutionController → JobQueue.
  - When OFF, behavior remains the same as the pre-queue path (direct run).
- Adds **job-state callbacks → GUI**:
  - Maps job lifecycle states (QUEUED, RUNNING, COMPLETED, FAILED, CANCELLED) into controller lifecycle and GUI-facing status updates (Idle, Queued, Running, Completed, Failed).
- Extends the test suite:
  - Controller tests for queue-backed execution and lifecycle transitions.
  - Queue integration tests focused on controller contracts (not re-testing queue core logic).
  - Optional GUI V2 harness tests that assert Run-button behavior correctly routes into the queue-backed path when enabled.
- Updates the rolling summary and relevant docs so Codex treats QueueExecutionController as the canonical controller–queue bridge going forward.

This PR is a **controller integration and wiring** step. It does not change individual pipeline stages, learning behavior, or the JobQueue core logic, and it keeps GUI V2 behavior identical by default (queue-backed mode is feature-flagged).

---

## Files touched

> Names may vary slightly; keep logic within these responsibilities and avoid expanding scope beyond controller/queue/GUI wiring.

### Controller

- `src/controller/queue_execution_controller.py` **(new)**
  - Defines a `QueueExecutionController` (final name may vary but must live in the controller layer) responsible for:
    - Holding references to:
      - `JobQueue`
      - `SingleNodeJobRunner` (or an injected job runner abstraction)
    - Providing a narrow, controller-friendly API:
      - `submit_pipeline_job(config: PipelineConfig) -> str`
      - `cancel_job(job_id: str) -> None`
      - `get_job_status(job_id: str) -> JobStatus`
      - Optional subscription/callback registration mechanisms so controllers can be notified when job states change.
  - Enforces v2 architecture rules:
    - No GUI imports.
    - No direct pipeline stage imports.
    - No subprocess or network calls; those live in pipeline/api layers.

- `src/controller/pipeline_controller.py`
  - Integrates with `QueueExecutionController`:
    - Adds an **optional** queue-backed execution path controlled via a config/feature flag:
      - `use_queue_execution: bool` (or similarly named field in app config).
    - For `run_pipeline` or its v2 equivalent:
      - If `use_queue_execution` is **false**:
        - Preserve existing direct execution semantics (as wired by PR-#36).
      - If `use_queue_execution` is **true**:
        - Build `PipelineConfig` (likely via the assembler from PR-#38).
        - Call `queue_execution_controller.submit_pipeline_job(config)` to obtain a job id.
        - Store `active_job_id` (and possibly `active_job_token`).
        - Set controller lifecycle to RUNNING/QUEUED as appropriate.
    - For Stop/Cancel:
      - If a queue-backed job is active:
        - Call `queue_execution_controller.cancel_job(active_job_id)` instead of directly canceling the worker.
    - Adds glue methods to handle job lifecycle callbacks:
      - `on_job_status_changed(job_id: str, status: JobStatus) -> None`
        - Translates queue-level status into controller lifecycle:
          - QUEUED → state = RUNNING (but GUI may show “Queued” in text)
          - RUNNING → state = RUNNING
          - COMPLETED → state = IDLE
          - FAILED → state = ERROR
          - CANCELLED → state = IDLE or STOPPING→IDLE, depending on existing patterns.

- `src/controller/state.py` (if present)
  - May define or extend:
    - Controller lifecycle states and their mapping from job statuses.
  - Must avoid introducing new states not justified by `ARCHITECTURE_v2_COMBINED.md`.

### Queue (integration only)

- `src/queue/job_queue.py`
  - Optional, minimal additions to support:
    - Lookups by `job_id` that the `QueueExecutionController` might need for status queries or cancellation.
  - No changes to priority or FIFO semantics introduced in PR-#35.

- `src/queue/single_node_runner.py`
  - Optional integration hooks:
    - Accept optional callbacks or hooks that `QueueExecutionController` can register to observe:
      - When a job transitions RUNNING → COMPLETED / FAILED / CANCELLED.
  - These hooks should be:
    - Generic and job-focused (no controller references).
    - Safe to use when multiple controllers or future cluster features are added.

### GUI V2 (feature-flag-aware wiring only)

- `src/gui/main_window.py`
  - Adds an awareness of whether:
    - Queue-backed execution is **enabled** for this session (read from config via controller).
  - For the Run button callback:
    - Continues to call the same controller method (e.g., `on_run_pipeline_requested()`).
    - No direct queue or job imports; all logic remains via controller.
  - Adds minimal, optional visual feedback for job states if the controller exposes them (e.g., status text “Queued”).
    - If this is too much for this PR, keep GUI strictly behaviorally identical and allow only the test harness to inspect status.

No layout or theme changes — only wiring/context awareness.

### Config / project context

- `src/utils/app_config.py` (or analogous)
  - Adds a feature flag, e.g.:
    - `queue_execution_enabled: bool = False` by default.
  - Provides getter/setter or read-only access for controllers and GUI to check.

### Tests

- `tests/controller/test_queue_execution_controller.py` **(new)**
  - Unit tests for `QueueExecutionController`:
    - Submitting a pipeline job:
      - Calls into `JobQueue` with payload containing the `PipelineConfig`.
      - Returns a consistent job id.
    - Job status queries:
      - Use a fake or in-memory job queue with pre-seeded job statuses to verify mapping.
    - Cancellation:
      - Calls `cancel_job(job_id)` on the queue abstraction.
  - Uses mocks/fakes for `JobQueue` and `SingleNodeJobRunner`; no real threads or long-running loops.

- `tests/controller/test_pipeline_controller_queue_mode.py` **(new)**
  - Scenarios:
    1. **Queue mode disabled**
       - With `queue_execution_enabled = False`:
         - Ensure `run_pipeline` uses direct execution (as configured in PR-#36).
         - No calls to `QueueExecutionController`.
    2. **Queue mode enabled**
       - With `queue_execution_enabled = True`:
         - Pressing Run:
           - Leads to `submit_pipeline_job(...)` call.
           - Stores `active_job_id`.
         - Simulate job lifecycle callbacks from `QueueExecutionController` into `PipelineController`:
           - QUEUED → state RUNNING + optional “Queued” annotation.
           - RUNNING → state RUNNING.
           - COMPLETED → state IDLE (and any “run completed” callbacks to GUI are fired).
           - FAILED → state ERROR (error surfaced appropriately).
           - CANCELLED → STOPPING → IDLE or direct IDLE, per existing expectations.
  - No GUI imports in these tests; they operate directly on controllers.

- `tests/gui_v2/test_run_button_queue_mode_toggle.py` **(new, optional but recommended)**
  - Uses a GUI V2 harness (like in PR-#39) to:
    - Configure the app with:
      - `queue_execution_enabled = False` → pressing Run uses direct mode (fake controller).
      - `queue_execution_enabled = True` → pressing Run calls into a fake controller that records job submission calls.
    - Assert:
      - Run button uses the same controller hook in both modes.
      - The difference is only in whether the controller calls `QueueExecutionController` or direct-run logic.

---

## Behavioral changes

- **Default behavior (queue execution disabled)**
  - For most users, nothing changes:
    - Run button:
      - Still triggers the same controller method.
      - Still runs the pipeline with the existing queue-backed or direct semantics set in PR-#36.
    - There is no visible indication that a job queue is involved unless future GUI PRs add queue views.
  - This keeps risk low while we prove out the integration.

- **Queue execution enabled (feature flag)**
  - When `queue_execution_enabled` is true:
    - The controller:
      - Creates a `PipelineConfig`.
      - Submits it as a job via `QueueExecutionController`.
      - Tracks job id and monitors its progress through job statuses.
    - GUI:
      - Receives status updates via existing controller callbacks:
        - “Queued” (optional text label).
        - “Running”.
        - “Completed”.
        - “Failed”.
    - Stop/Cancel:
      - Invokes job cancellation rather than direct thread cancellation.

- **Non-goals**
  - This PR does **not**:
    - Provide a user-facing panel for job queue inspection (that’s a later GUI PR).
    - Implement multi-node or remote worker logic (that is guided by `Cluster_Compute_Vision_v2` and will be addressed in later queue/cluster PRs).
    - Alter pipeline logic, learning hooks, or API contract.

---

## Risks / invariants

- **Invariants**
  - Controller remains the **only** owner of application lifecycle and run state, as defined in `ARCHITECTURE_v2_COMBINED.md`:
    - GUI does not talk directly to the queue layer.
    - Queue and pipeline do not depend on GUI.
  - Queue semantics (priority + FIFO) remain as defined in PR-#35:
    - `QueueExecutionController` must not reorder jobs itself.
  - `PipelineConfig` is the only container for stage configuration and must continue to conform to `PIPELINE_RULES.md`:
    - No separate ad-hoc config dicts used for jobs.
  - Learning remains opt-in and unaffected:
    - Jobs carry `PipelineConfig` that includes learning flags; LearningRecord behavior is unchanged from PR-#33 / PR-#34.

- **Risks**
  - If callbacks between `QueueExecutionController` and `PipelineController` are miswired, the controller/GUI may:
    - Get stuck in RUNNING state after job completion.
    - Treat CANCELLED as FAILED or vice versa.
  - If feature flag logic is incorrect:
    - The app might inadvertently switch to queue mode before it’s fully validated.
  - Concurrency subtleties:
    - If job-state callbacks are invoked from worker threads, they must be marshalled safely back into the main thread / GUI-safe context.

- **Mitigations**
  - Keep `QueueExecutionController` small and unit-tested.
  - Ensure that:
    - Controller → GUI signals are emitted in the main thread (e.g., via Tk `after()` in existing patterns).
  - Default `queue_execution_enabled` to `False` and only enable it explicitly in configuration or test harnesses.
  - Extend tests to cover the full range of job statuses and controller state transitions.

---

## Tests

Run at minimum:

- Controller-specific:
  - `pytest tests/controller/test_queue_execution_controller.py -v`
  - `pytest tests/controller/test_pipeline_controller_queue_mode.py -v`

- GUI V2 (if queue mode toggle tests are added):
  - `pytest tests/gui_v2/test_run_button_queue_mode_toggle.py -v`

- Regression / integration:
  - `pytest tests/queue -v`
  - `pytest tests/controller -v`
  - `pytest tests/gui_v2 -v`
  - `pytest -v`

Expected results:

- New tests confirm:
  - QueueExecutionController submits jobs and queries statuses correctly.
  - PipelineController correctly switches between direct and queue-backed execution based on the feature flag.
  - Job lifecycle transitions map correctly into controller lifecycle states.
- Existing queue and controller tests remain green; no regressions in job model, JobQueue behavior, or SingleNodeJobRunner.

---

## Migration / future work

With `QueueExecutionController` in place, future PRs can safely extend queue-based behavior without touching the GUI or low-level queue implementation:

- **Job visibility and control in GUI:**
  - Add a Job/Queue panel:
    - Show queued, running, completed, and failed jobs.
    - Allow re-trying or inspecting job results.
- **Cluster integration:**
  - Reuse the controller–queue contracts to:
    - Route jobs to different workers.
    - Surface worker/node status.
    - Coordinate multi-node scheduling as described in `Cluster_Compute_Vision_v2`.
- **Learning and randomizer integration:**
  - Use job metadata to:
    - Drive learning runs (batch jobs for learning plans).
    - Schedule randomizer “matrix” runs through the job queue.
- **Job persistence:**
  - Build on top of this controller-level abstraction to add persistent job history (e.g., JSONL or SQLite-backed) without changing GUI run behavior.

By isolating queue semantics and controller wiring in this PR, later work can be focused on new features rather than retrofitting basic execution flow.

---

## Rolling summary update (for `docs/codex_context/ROLLING_SUMMARY.md`)

Append under the appropriate date heading (e.g., `## 2025-11-22`):

- Introduced a dedicated **QueueExecutionController** in the controller layer to own queue-backed job submission, status queries, and cancellation, bridging `JobQueue`/`SingleNodeJobRunner` with the rest of the controller stack.
- Extended `PipelineController` with a feature-flagged **queue execution mode**, allowing GUI runs to be executed as queued jobs without changing default behavior.
- Added controller-level tests to validate job lifecycle mappings (QUEUED/RUNNING/COMPLETED/FAILED/CANCELLED → controller lifecycle), and ensured GUI V2 can be wired to this mode in a test-safe, architecture-compliant way.
