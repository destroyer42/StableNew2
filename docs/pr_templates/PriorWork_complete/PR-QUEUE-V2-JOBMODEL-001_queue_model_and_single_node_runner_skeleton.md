# PR-QUEUE-V2-JOBMODEL-001
**Title:** Queue Model & Single-Node Job Runner Skeleton (Cluster-Ready, No Networking Yet)

## 1. Intent & Scope

This PR introduces the **foundational job/queue model** for StableNew’s future cluster scheduler (C3), while still running **entirely on a single node**.

It will:

- Define the core **Job** and **JobQueue** abstractions.
- Provide a **single-node JobRunner** that executes jobs by delegating to the existing PipelineController/PipelineRunner.
- Add dry-run tests and a basic CLI/dev-only entrypoint (if desired) for submitting jobs to the queue.

It will **not**:

- Add real multi-node/networked workers.
- Change GUI behavior (GUI can remain unaware in this PR).
- Change pipeline semantics (same PipelineConfig, same PipelineRunner).

Baseline: **StableNew-main-11-22-2025-0729.zip** plus completed PRs up through:

- PR-PIPELINE-V2-EXECUTOR-STAGEEVENTS-003
- PR-LEARN-V2-RECORDWRITER-001 (optional but assumed)
- PR-GUI-V2-LEARNING-ENTRYPOINT-001 (does not directly interact).

---

## 2. Goals

1. Introduce a **Job model** that encapsulates:
   - A pipeline config (or reference to a preset + overrides).
   - Optional learning and randomizer metadata.
   - Job id, timestamps, priority, and status.
2. Implement an in-memory **JobQueue** with basic operations:
   - Submit job.
   - Get next job (respecting priority).
   - Mark job running/completed/failed.
3. Implement a **SingleNodeJobRunner** that:
   - Pulls jobs from the queue in a worker thread.
   - Executes them via existing controller/pipeline runner.
   - Updates job status and captures results (output paths, errors).
4. Provide tests that simulate multiple jobs and validate:
   - Ordering and priority behavior.
   - Proper status transitions.
   - Clean shutdown semantics.

Non-goal: Exposing this queue in GUI; that will come later once the model is stable.

---

## 3. Allowed Files to Modify

New modules (preferred under a dedicated namespace):

- `src/queue/job_model.py`
- `src/queue/job_queue.py`
- `src/queue/single_node_runner.py`

Existing modules (minimal integration):

- `src/controller/pipeline_controller.py` (optional: thin adapter for running a PipelineConfig as a job)
- `src/config/app_config.py` (optional: dev flags for enabling queue-based execution)

Tests:

- `tests/queue/test_job_model.py`
- `tests/queue/test_job_queue_basic.py`
- `tests/queue/test_single_node_runner_loopback.py`

Docs:

- `docs/Cluster_Compute_Vision_v2.md` (mark initial job/queue implementation as started)
- `docs/Testing_Strategy_v2.md` (add queue test sections)

You MUST NOT:

- Touch GUI modules or tests.
- Add any real networking (no sockets, HTTP).
- Modify randomizer or learning behavior (beyond optional metadata fields on Job).

---

## 4. Implementation Plan

### 4.1 Job model

In `src/queue/job_model.py` define a simple dataclass (or similar) for Job:

```python
@dataclass
class Job:
    job_id: str
    created_at: datetime
    updated_at: datetime
    priority: JobPriority
    status: JobStatus  # QUEUED, RUNNING, COMPLETED, FAILED, CANCELLED
    pipeline_config: PipelineConfig
    learning_enabled: bool
    randomizer_metadata: Optional[RandomizerMetadata] = None
    error_message: Optional[str] = None
```

Define `JobPriority` and `JobStatus` enums.

Job should be **serializable** to a dict for future persistence, but persistence is out of scope here.

### 4.2 JobQueue

In `src/queue/job_queue.py` implement an in-memory queue:

- API examples:

```python
class JobQueue:
    def submit(self, job: Job) -> None: ...
    def get_next_job(self) -> Optional[Job]: ...
    def mark_running(self, job_id: str) -> None: ...
    def mark_completed(self, job_id: str) -> None: ...
    def mark_failed(self, job_id: str, error_message: str) -> None: ...
    def list_jobs(self, status_filter: Optional[JobStatus] = None) -> List[Job]: ...
```

- Handle priority via a simple ordering rule:
  - Higher priority jobs are always retrieved before lower priority ones.
  - Within the same priority, use FIFO order.

- This can be implemented via a heap or two-level structure; keep it simple and well-tested.

### 4.3 SingleNodeJobRunner

In `src/queue/single_node_runner.py`:

- Implement a class that:
  - Owns a JobQueue reference.
  - Runs a worker loop in a background thread that:
    - Calls `get_next_job()`.
    - Marks job as RUNNING.
    - Executes it via PipelineController or a thin adapter (e.g., `run_job(job)`).
    - Captures outputs and error messages.
    - Marks job as COMPLETED or FAILED.
  - Honors a cancel/stop flag for clean shutdown.

- The runner should be able to be started/stopped from tests without requiring the GUI or network:

```python
runner = SingleNodeJobRunner(job_queue, pipeline_runner_adapter)
runner.start()
...
runner.stop()
```

### 4.4 Controller/Pipeline adapter (minimal)

If needed, add a small adapter in `pipeline_controller` or a dedicated helper that:

- Accepts a `PipelineConfig` and a CancelToken (or creates one).
- Runs the pipeline synchronously (no GUI) using the existing PipelineRunner.
- Returns a simple result object with:
  - success/failure
  - output root path
  - optional error message

This should reuse the existing pipeline machinery; do not duplicate logic.

### 4.5 Tests

Add queue tests:

1. `test_job_queue_respects_priority_and_fifo`:
   - Submit several jobs with mixed priorities and assert retrieval order.

2. `test_job_queue_status_transitions`:
   - Submit, mark running/completed/failed; assert status and timestamps update correctly.

3. `test_single_node_runner_executes_jobs_and_updates_status`:
   - Use a fake pipeline adapter that simulates work and errors; assert job status updates accordingly.

Ensure queue tests do not rely on Tk or network.

---

## 5. Commands & Expected Outcomes

You MUST run:

- `pytest tests/queue -v`
- `pytest tests/pipeline -v`
- `pytest tests/controller -v`
- `pytest -v`

All tests must pass; queue tests should be fast and deterministic.

---

## 6. Acceptance Criteria

This PR is complete when:

1. A Job and JobQueue abstraction exists with solid unit tests.
2. SingleNodeJobRunner can execute jobs in a background thread and update job status correctly.
3. The implementation is single-node only with no networking.
4. No GUI code has been modified.
5. Docs acknowledge that the first step of the C3 queue/worker architecture is in place.
