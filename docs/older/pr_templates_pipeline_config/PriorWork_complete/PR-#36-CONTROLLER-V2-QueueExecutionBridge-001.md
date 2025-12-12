Timestamp: 2025-11-22 17:30 (UTC-06)
PR Id: PR-#36-CONTROLLER-V2-QueueExecutionBridge-001
Spec Path: docs/pr_templates/PR-#36-CONTROLLER-V2-QueueExecutionBridge-001.md

# PR-#36-CONTROLLER-V2-QueueExecutionBridge-001: Queue-backed pipeline execution (controller integration)

## What’s new

- Switched StableNew’s controller execution path from direct `PipelineRunner` calls to a **queue-backed model** using the `JobQueue` and `SingleNodeJobRunner` introduced in PR-#35.
- Introduced a `JobExecutionController` (or equivalent orchestration layer) that owns job submission, cancellation, and lifecycle callbacks, while respecting the v2 controller responsibilities defined in the architecture docs.
- Updated `PipelineController` to submit pipeline runs as jobs, track the active job id, and translate job lifecycle updates into controller lifecycle states (IDLE, RUNNING, STOPPING, ERROR).
- Added integration glue so `SingleNodeJobRunner` executes jobs via `PipelineRunner` with the existing learning hooks and stage events, preserving Learning v2 behavior from PR-#33 and GUI learning entrypoints from PR-#34.
- Extended controller/queue tests to cover job submission, lifecycle transitions, and controller–queue–runner integration, ensuring this queue-backed flow is the new single-node default.

This PR is a **controller-only integration step**: behavior from the GUI’s perspective is unchanged, but all pipeline work now flows through the queue/runner foundation instead of a direct controller → pipeline call.

---

## Files touched

> Exact file names may vary slightly; adjust to match the existing v2 layout and imports.

### Controller

- `src/controller/pipeline_controller.py`
  - Replace direct `PipelineRunner` invocations with job submission calls.
  - Track `active_job_id` instead of direct worker-thread handles.
  - Translate job lifecycle updates into controller lifecycle states.

- `src/controller/job_execution_controller.py` **(new)**
  - Centralized orchestration between controller(s), `JobQueue`, and `SingleNodeJobRunner`.
  - Public surface along the lines of:
    - `submit_pipeline_run(config: PipelineConfig) -> str`
    - `cancel_job(job_id: str) -> None`
    - `get_job_status(job_id: str) -> JobStatus`

- `src/controller/state.py` (if present and appropriate)
  - Minor extensions to represent job-linked lifecycle transitions (e.g., mapping JobStatus → controller lifecycle).

- `src/controller/cancel_token.py` (if needed)
  - Minor updates to ensure cancel semantics align with job cancellation, not direct pipeline-thread cancellation.

### Queue

- `src/queue/job_queue.py`
  - Small additions to support status inspection / callbacks needed by `JobExecutionController` (no behavioral changes to core queue invariants).

- `src/queue/single_node_runner.py`
  - Ensure the runner:
    - Invokes the injected “execute job” callable (backed by `PipelineRunner`) with the job payload.
    - Updates job status (RUNNING/COMPLETED/FAILED/CANCELLED).
    - Optionally exposes hooks for lifecycle callbacks into the controller layer.

### Pipeline (adapter only)

- `src/pipeline/pipeline_runner.py`
  - Adapter-only changes for the controller/runner contract, such as:
    - A small helper like `run_for_job(config: PipelineConfig, cancel_token: CancelToken, learning_hooks: Optional[...])`.
  - No changes to stage logic, tiling, or pipeline rules.

### Tests

- `tests/controller/test_controller_queue_execution.py` **(new)**
  - Verifies the controller submits a job, receives a job id, and transitions IDLE → RUNNING → IDLE on success.

- `tests/controller/test_controller_job_lifecycle.py` **(new)**
  - Exercises job status transitions (QUEUED/RUNNING/COMPLETED/FAILED/CANCELLED) and maps them to controller lifecycle states.

- `tests/queue/test_jobrunner_integration.py` **(new or extended)**
  - Validates that `SingleNodeJobRunner` executes jobs via the injected callable and updates job status, with controller observing the transitions.

---

## Behavioral changes

- From the GUI perspective:
  - The **Run** and **Stop/Cancel** buttons behave the same as before.
  - Pipeline progress, completion, and error reporting still surface through the same controller-driven callbacks.
  - Learning v2 behavior (passive JSONL LearningRecords and GUI learning review) remains intact.

- Under the hood:
  - A GUI-triggered run is converted into a `Job` with a unique job id and submitted to `JobQueue`.
  - `SingleNodeJobRunner` retrieves jobs, calls into `PipelineRunner` to execute them, and updates job status.
  - `PipelineController`:
    - Tracks the active job id for the current run.
    - Uses job status changes to drive lifecycle changes (IDLE/RUNNING/STOPPING/ERROR).
    - Uses job cancellation instead of directly canceling a worker thread when the user hits Stop/Cancel.

- Queue semantics:
  - Even though we still only run on a single node, the queue is now the **authoritative execution path**:
    - Jobs are queued in priority/FIFO order as defined in PR-#35.
    - Future PRs can add multi-job scenarios (e.g., batch runs, scheduled jobs) without changing GUI behavior.

---

## Risks / Invariants

- Invariants that must hold:
  - GUI → controller contract does **not** change:
    - Same public methods for “run pipeline” and “stop/cancel”.
    - Same callback contracts for progress and completion.
  - Pipeline invariants remain unchanged and must still follow `PIPELINE_RULES.md`:
    - Same stage ordering and toggle behavior.
    - Same safety limits for megapixels and upscale tiles.
    - Same deterministic behavior and logging expectations.
  - Learning remains opt-in and safe:
    - If learning is disabled, no LearningRecords are written.
    - If learning is enabled, LearningRecord builder/writer semantics are unchanged and still align with `LEARNING_SYSTEM_SPEC.md`.
  - No GUI layer imports in `queue` or `controller` modules; v2 layering must match `ARCHITECTURE_v2_COMBINED.md`.

- Primary risk areas:
  - Subtle race conditions between controller lifecycle state and job status transitions.
  - Mis-mapping of job statuses (e.g., FAILED vs CANCELLED) into controller states (ERROR vs STOPPING/IDLE).
  - Regression in Stop/Cancel behavior if job cancellation does not correctly propagate to `PipelineRunner` / CancelToken.

- Mitigations:
  - Focused controller + queue integration tests for all lifecycle combinations.
  - No changes to pipeline stages or GUI code in this PR.
  - Strict adherence to the architecture and coding standards docs:
    - Controller owns lifecycle; queue/runner own job execution; pipeline remains headless.

---

## Tests

Run, at minimum:

- Controller tests:
  - `pytest tests/controller/test_controller_queue_execution.py -v`
  - `pytest tests/controller/test_controller_job_lifecycle.py -v`

- Queue tests:
  - `pytest tests/queue/test_jobrunner_integration.py -v`
  - `pytest tests/queue -v`

- Full suite:
  - `pytest -v`

Expected outcomes:

- All new tests should pass and demonstrate:
  - Correct job submission + execution.
  - Proper mapping of JobStatus to controller lifecycle states.
- Existing tests in `tests/pipeline`, `tests/gui_v2`, `tests/learning`, etc. must remain green with no behavioral regressions.

If any existing tests fail, adjust the controller/queue integration first; do not “fix” the tests unless the change in behavior is intentional and explicitly documented in this PR.

---

## Migration / Notes for future PRs

- This PR completes the **single-node queue integration**:
  - All controller-driven runs now go through `JobQueue` + `SingleNodeJobRunner`.

- Future work will build on this foundation:
  - PR-#37+ (Cluster/Worker integration):
    - Introduce worker descriptors (GPU capabilities, load).
    - Allow the queue to target different workers (multi-node).
    - Align with the “Cluster & IO Layer” vision in the architecture doc.
  - PRs for:
    - Batch/learning runs scheduled via jobs (LearningPlan → Jobs).
    - Persistence of job history and job inspection UI.
    - Optional GUI surfaces for “job queue” and “job history” views.

- For now, single-node behavior is the only supported mode; cluster/remote worker use will be explicitly added in later PRs.

---

## Rolling summary update (for `docs/codex_context/ROLLING_SUMMARY.md`)

Add the following bullets under a new date heading for the day this PR lands (or merge into the existing 2025-11-22 section if appropriate):

- Integrated the **JobQueue + SingleNodeJobRunner** foundation into the controller layer so all pipeline runs now execute as queue-backed jobs instead of direct controller → pipeline calls.
- Introduced a `JobExecutionController` (or equivalent) responsible for job submission, cancellation, and lifecycle mapping into controller states.
- Preserved existing GUI behavior while enabling future cluster work (multi-job scheduling, multi-node workers) without changing the GUI or pipeline semantics.
