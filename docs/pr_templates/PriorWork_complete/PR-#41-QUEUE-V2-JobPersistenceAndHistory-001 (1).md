Timestamp: 2025-11-22 19:30 (UTC-06)
PR Id: PR-#41-QUEUE-V2-JobPersistenceAndHistory-001
Spec Path: docs/pr_templates/PR-#41-QUEUE-V2-JobPersistenceAndHistory-001.md

# PR-#41-QUEUE-V2-JobPersistenceAndHistory-001: Persistent Job History and Queue Introspection API

## What’s new

- Introduces a **persistent job history layer** for the queue subsystem so that jobs survive process restarts and can be inspected after completion.
- Adds a thin, well-defined **JobHistoryStore** abstraction (backed initially by JSONL or SQLite) that records:
  - Job metadata (id, timestamps, payload summary).
  - Job status transitions (QUEUED, RUNNING, COMPLETED, FAILED, CANCELLED).
  - Optional error messages and basic result references.
- Extends the queue layer with a **Queue Introspection API** that:
  - Lists active/queued jobs from `JobQueue`.
  - Lists recent jobs from `JobHistoryStore` with filtering/paging capabilities.
- Exposes a controller-facing **JobHistory/Queue view model** that GUI and tools can call without knowing storage details.
- Adds tests for:
  - Job history persistence behavior.
  - Introspection queries (filtering, status selection, ordering).
- Updates docs & rolling summary so Codex treats this as the canonical source for persistent job history before any GUI panels or cluster-aware features are built.

This PR is a **queue + controller service** change only. It does not add a GUI panel; instead, it provides the backend APIs that the GUI will consume in a later PR.

---

## Files touched

> Adjust module names to match the actual repo layout; keep responsibilities within these boundaries.

### Queue / persistence

- `src/queue/job_history_store.py` **(new)**
  - Defines an abstraction like:

    - `class JobHistoryStore(Protocol or base class):`
      - `record_job_submission(job: Job) -> None`
      - `record_status_change(job_id: str, status: JobStatus, ts: datetime, error: Optional[str] = None) -> None`
      - `list_jobs(status: Optional[JobStatus] = None, limit: int = 50, offset: int = 0) -> List[JobHistoryEntry]`
      - `get_job(job_id: str) -> Optional[JobHistoryEntry]`

  - Introduces a concrete implementation, e.g., `JSONLJobHistoryStore` or `SQLiteJobHistoryStore`, with:
    - Append-only semantics for history (no in-place partial writes).
    - Compact summary of job payloads (e.g., prompt + model name) to avoid bloating entries.

  - Defines `JobHistoryEntry` dataclass with:
    - `job_id: str`
    - `created_at: datetime`
    - `started_at: Optional[datetime]`
    - `completed_at: Optional[datetime]`
    - `status: JobStatus`
    - `payload_summary: str`
    - `error_message: Optional[str]`

- `src/queue/job_queue.py`
  - Integrates with `JobHistoryStore` by:
    - Calling `record_job_submission(job)` when a job is enqueued.
    - Optionally exposing hooks used by the runner to record status transitions.

- `src/queue/single_node_runner.py`
  - On job state changes (RUNNING, COMPLETED, FAILED, CANCELLED):
    - Calls into `JobHistoryStore.record_status_change(...)` via an injected `JobHistoryStore` or a small mediator object.
  - No changes to execution semantics or queue ordering.

### Controller / service layer

- `src/controller/job_history_service.py` **(new)**
  - Provides a controller-friendly service that:
    - Wraps `JobHistoryStore` and `JobQueue`.
    - Exposes methods like:
      - `list_active_jobs() -> List[JobViewModel]`
      - `list_recent_jobs(limit: int = 50, status: Optional[JobStatus] = None) -> List[JobViewModel]`
      - `get_job(job_id: str) -> Optional[JobViewModel]`
    - Converts internal history entries + live queue entries into a stable **view model** for GUI/tools:
      - `JobViewModel` fields:
        - `job_id: str`
        - `status: JobStatus`
        - `created_at, started_at, completed_at`
        - `payload_summary: str`
        - `is_active: bool`
        - Optional: `last_error: Optional[str]`

  - Lives strictly in controller layer:
    - No GUI imports.
    - No direct persistence-coded paths in GUI or queue.

- `src/controller/queue_execution_controller.py` (if present from PR-#40)
  - Integrates with `JobHistoryStore` and `JobHistoryService` where appropriate:
    - Ensures new job submissions and lifecycle callbacks continue to update `JobHistoryStore`.
    - May expose convenience methods that delegate to `JobHistoryService`.

### Config / utils

- `src/utils/app_config.py` or similar:
  - Adds configuration values for:
    - Job history backend path (e.g., `job_history_path: str` for JSONL, or SQLite file).
    - Basic retention/limit settings (e.g., max history entries before compaction; can be a TODO for future PRs).

### Docs

- `docs/Cluster_Compute_Vision_v2.md`
  - Update the Queue/Job section to mention:
    - JobHistoryStore as the canonical job history mechanism.
    - Queue introspection and history as prerequisites for:
      - Cluster dashboards.
      - job/queue GUI panels.
      - production diagnostics.

- `docs/ARCHITECTURE_v2_COMBINED.md`
  - Extend the Queue + Controller sections:
    - Queue owns in-memory scheduling.
    - JobHistoryStore owns persistent history.
    - JobHistoryService in controller exposes queue/history info to GUI & tools.

- `docs/codex_context/ROLLING_SUMMARY.md`
  - Updated as described in the rolling summary section below.

---

## Behavioral changes

- For end users:
  - No immediate GUI-visible change in this PR.
  - Future releases can add:
    - “Recent jobs” panels.
    - Diagnostics pages.
    - Job inspection UIs.
  - Internally, job runs now leave a persistent trail that can be analyzed and surfaced later.

- For developers / tools:
  - Jobs are no longer in-memory-only:
    - Each submission and state change is recorded in history.
    - Queue introspection API allows controllers and tools to:
      - List active jobs (from JobQueue).
      - Retrieve recent jobs (from JobHistoryStore).
  - When debugging:
    - It’s possible to fetch job details by id and inspect basic metadata and error messages.

- Queue status + persistence:
  - In-memory JobQueue remains the source of truth for:
    - Current execution ordering.
    - Active/queued job set.
  - JobHistoryStore is the source of truth for:
    - Historical status.
    - Metadata for completed/cancelled/failed jobs.

---

## Risks / invariants

- **Invariants**
  - JobQueue behavior:
    - Priority and FIFO semantics remain unchanged from PR-#35.
    - JobHistoryStore must not interfere with scheduling decisions (no synchronous, blocking operations that stall queue operations).
  - Persistence:
    - Job history writes must be robust:
      - Append-only (for JSONL) or transactional (for SQLite).
      - Failures to write history must not crash the process or prevent job execution.
  - Layering:
    - GUI never imports JobHistoryStore directly.
    - Queue layer never imports GUI.
    - Controller stays the only bridge between GUI and queue/history layers, in line with `ARCHITECTURE_v2_COMBINED.md`.

- **Risks**
  - I/O or disk errors in JobHistoryStore could:
    - Cause partial job history.
    - Introduce slowdowns if not handled carefully.
  - Concurrency issues:
    - If multiple threads update history simultaneously, store implementation must be thread-safe.
  - Data growth:
    - Job history can grow unbounded if no retention policy is implemented.

- **Mitigations**
  - Keep JobHistoryStore implementation simple and:
    - Use locks around write operations.
    - Catch and log I/O errors without interrupting job execution.
  - Start with a modest, configurable history retention plan (e.g., “keep last N entries” or “compact on startup”), even if full compaction logic is a future PR.
  - Ensure tests cover concurrent write scenarios at a basic level.

---

## Tests

Run at minimum:

- Job history unit tests:
  - `pytest tests/queue/test_job_history_store.py -v`
    - Verifies:
      - Submission + status change record correctly.
      - Listing and filtering work as expected.
      - Job lookups by id return correct entries.

- Controller history/introspection:
  - `pytest tests/controller/test_job_history_service.py -v`
    - Verifies:
      - JobHistoryService correctly merges active queue jobs and historical entries into JobViewModel objects.
      - Status filters and limits behave as expected.

- Queue regression:
  - `pytest tests/queue -v`

- Full suite:
  - `pytest -v`

Expected results:

- New tests validate:
  - Persistent history behavior.
  - Introspection contracts from controller.
- Existing tests (queue, controller, GUI V2, pipeline, learning) remain green; this PR must not alter execution semantics or GUI wiring.

---

## Migration / future work

This PR is the foundation for:

- **GUI job/queue panels**:
  - A future GUI V2 PR can use JobHistoryService to:
    - Show recent/completed jobs.
    - Provide detail views on individual jobs.
- **Cluster-aware dashboards**:
  - JobHistoryStore becomes the core dataset for:
    - Performance dashboards.
    - Worker node utilization.
    - Learning about model usage patterns.
- **Advanced features**:
  - Retry jobs (using job history entries).
  - Tagging and grouping jobs (by prompt pack, project, or learning plan).
  - Exporting job history for offline analytics.

---

## Rolling summary update (for `docs/codex_context/ROLLING_SUMMARY.md`)

Append under the appropriate date (e.g., `## 2025-11-22`):

- Introduced a **JobHistoryStore** abstraction and initial implementation to persist job metadata and status transitions outside of memory.
- Added a controller-facing **JobHistoryService** that exposes unified views of active and historical jobs for future GUI panels and diagnostics.
- Ensured JobQueue behavior stays unchanged while extending the queue subsystem with introspection and persistence capabilities aligned with the cluster/queue vision.
