Timestamp: {timestamp}
PR Id: PR-#44-CLUSTER-V2-WorkerRegistryAndLocalWorker-001
Spec Path: docs/pr_templates/PR-#44-CLUSTER-V2-WorkerRegistryAndLocalWorker-001.md

# PR-#44-CLUSTER-V2-WorkerRegistryAndLocalWorker-001: Worker Registry and Local Worker Descriptor (Cluster V2 Foundation)

## What’s new

- Introduces a **Worker Registry** abstraction as the first concrete step towards Cluster V2:
  - Defines how StableNew identifies, describes, and tracks **workers** (nodes capable of running jobs).
- Defines a **LocalWorkerDescriptor** for the current node:
  - Captures its capabilities (GPU count, VRAM, tags, and so on).
  - Provides a stable identity for job assignment decisions.
- Adds a minimal **WorkerRegistry** implementation that:
  - Starts with a single local worker entry.
  - Provides methods to list, update, and flag worker availability.
- Extends queue/controller integration so:
  - Jobs can be associated with a target worker (initially, always the local worker).
  - Future PRs can implement multi-node scheduling and remote workers without changing core queue or GUI contracts.
- Adds tests that:
  - Validate worker registration and basic lifecycle (online/offline/maintenance).
  - Confirm that jobs recorded in JobHistory include a worker id or descriptor reference.

This PR is **cluster-plumbing only**: it does not introduce multi-node execution yet and does not change existing single-node behavior, but it lays the canonical foundation for worker-aware scheduling in later PRs.

---

## Files touched

> Names and paths may differ; adapt to the existing `cluster` / `queue` namespace.

### Cluster / worker abstractions

- `src/cluster/worker_model.py` **(new)**
  - Defines:
    - `WorkerId` type alias (such as `str`).
    - `WorkerStatus` enum:
      - `ONLINE`
      - `OFFLINE`
      - `MAINTENANCE`
      - Optionally `DEGRADED`
    - `WorkerDescriptor` dataclass with fields such as:
      - `id: WorkerId`
      - `name: str`
      - `is_local: bool`
      - `gpus: int`
      - `vram_gb: float` (approximate total VRAM)
      - `tags: List[str]` (for example, `["sdxl", "upscale"]`)
      - `status: WorkerStatus`
      - Optional:
        - `last_heartbeat: datetime`
        - `metadata: Dict[str, Any]` for extensibility.

  - Provides helper methods or functions for:
    - Constructing a **default LocalWorkerDescriptor** based on:
      - Config.
      - Optional runtime detection of GPU resources (may be deferred to future PRs; it is acceptable to stub now).

- `src/cluster/worker_registry.py` **(new)**
  - Defines a `WorkerRegistry` abstraction with methods:
    - `register_worker(descriptor: WorkerDescriptor) -> None`
    - `update_worker_status(worker_id: WorkerId, status: WorkerStatus) -> None`
    - `get_worker(worker_id: WorkerId) -> Optional[WorkerDescriptor]`
    - `list_workers(status: Optional[WorkerStatus] = None) -> List[WorkerDescriptor]`
    - `get_local_worker() -> WorkerDescriptor`
  - Provides an in-memory implementation:
    - Backed by a simple dict.
    - Thread-safe via a lock.
    - Optional future extension for persistence is allowed but not required here.

### Queue / job model integration

- `src/queue/job_model.py`
  - Adds a field:
    - `worker_id: Optional[WorkerId] = None`
  - Invariants:
    - Existing tests updated to expect default `worker_id=None` for now.
    - New jobs may set `worker_id` explicitly when scheduling to a specific worker.

- `src/queue/job_queue.py`
  - No change to scheduling semantics in this PR.
  - May add convenience hooks to:
    - Schedule jobs onto a specific worker id if or when scheduling logic is extended in later PRs.

### Controller

- `src/controller/cluster_controller.py` **(new or extended)**
  - Introduces a small controller responsible for:
    - Initializing the `WorkerRegistry` at app startup.
    - Registering the **local worker** descriptor.
    - Providing a controller-level facade for:
      - `list_workers()`
      - `get_local_worker()`
  - Exposes worker info to other controllers (for example, QueueExecutionController) without exposing cluster internals to GUI.

- `src/controller/queue_execution_controller.py`
  - Integrates worker awareness at a minimal level:
    - When submitting a job:
      - Attaches `worker_id` for the local worker (or leaves `None` if you prefer to postpone this).
    - No actual multi-worker routing or scheduling decisions; all jobs still run locally.

### Job history

- `src/queue/job_history_store.py` (from PR-#41)
  - Extends `JobHistoryEntry` to include:
    - `worker_id: Optional[WorkerId]`
  - Ensures:
    - Additionally records the worker id for each job in history.
  - Tests updated accordingly.

### Docs

- `docs/Cluster_Compute_Vision_v2.md`
  - Add a **Worker Model & Registry** section:
    - Describes:
      - WorkerDescriptor.
      - WorkerStatus.
      - WorkerRegistry responsibilities.
    - Clearly notes that:
      - This PR covers only local worker registration.
      - Remote or multi-node workers will be addressed in future PRs.

- `docs/ARCHITECTURE_v2_COMBINED.md`
  - Extend the cluster/queue sections to mention:
    - Worker Registry as the canonical source of worker metadata.
    - Jobs carrying `worker_id` as part of their contract.

- `docs/codex_context/ROLLING_SUMMARY.md`
  - Updated as described below.

---

## Behavioral changes

- For end users:
  - There is **no visible behavioral change**.
  - All jobs still execute on the local machine using the existing SingleNodeJobRunner.
  - This PR solely prepares the system for later multi-node features.

- For the system:
  - Workers:
    - The system now internally knows about the concept of **workers** and has a registered local worker.
  - Jobs:
    - Each job can be associated with a `worker_id`, which:
      - Currently defaults to the local worker for new jobs (if enabled).
      - Is stored in job history for later inspection.
  - Scheduling:
    - Still single-node; future PRs can build real scheduling on top.

---

## Risks / invariants

- **Invariants**
  - WorkerRegistry:
    - Must be thread-safe and deterministic.
    - Must always return a valid local worker descriptor when requested (once initialized).
  - Jobs:
    - Adding `worker_id` must not break existing queue tests or behavior.
    - Jobs without an explicit `worker_id` should be treated as “local” or “unassigned” in a backward-compatible way.
  - Layering:
    - GUI does not import WorkerRegistry or cluster modules directly.
    - Cluster modules must not depend on GUI.

- **Risks**
  - Future multi-node logic could:
    - Accidentally break single-node assumptions if worker selection is not carefully controlled.
  - Misconfigured local worker descriptor could:
    - Lead to confusing diagnostics if worker ids do not match across components.

- **Mitigations**
  - Keep this PR:
    - Strictly focused on models and an in-memory registry.
    - Without any experimental multi-node scheduling.
  - Ensure:
    - Tests cover WorkerRegistry behavior and `worker_id` propagation into job history.
  - Clearly document:
    - This PR as a foundational building block, not a behavior change.

---

## Tests

Run at minimum:

- Cluster / worker:
  - `pytest tests/cluster/test_worker_model_and_registry.py -v`
    - Validates:
      - WorkerDescriptor creation.
      - WorkerRegistry register/update/list behavior.
      - Local worker retrieval.

- Queue / job:
  - `pytest tests/queue/test_job_model.py -v`
    - Updated for `worker_id` field defaults.
  - `pytest tests/queue/test_job_history_store.py -v`
    - Validates that `worker_id` is recorded and retrievable.

- Controller:
  - `pytest tests/controller/test_cluster_controller.py -v`
    - Ensures:
      - Local worker registration at startup.
      - Worker listing APIs.

- Full regression:
  - `pytest -v`

Expected results:

- New tests validate:
  - Worker model and registry behavior.
  - `worker_id` propagation to job history.
- Existing queue/controller/pipeline/GUI tests remain green; single-node behavior unaffected.

---

## Migration / future work

This PR sets the stage for real Cluster V2 features:

- Future PRs can:
  - Add:
    - Remote worker descriptors (with network endpoints).
    - Heartbeat and health-check logic for workers.
    - Worker capability-based scheduling (for example, SDXL-only nodes).
  - Extend queue execution to:
    - Route jobs to different workers based on strategy.
  - Enhance job history:
    - Break down job counts per worker.
    - Show worker utilization in dashboards and GUI.

- Coordination with GUI:
  - Later PRs can allow:
    - Selecting a preferred worker (or “auto”) from the GUI.
    - Displaying worker health in diagnostics panels.

By solidifying the worker/registry model now, later changes can be incremental and safe.

---

## Rolling summary update (for `docs/codex_context/ROLLING_SUMMARY.md`)

Append under the appropriate date (for example, `## 2025-11-22`):

- Defined a **WorkerDescriptor** and **WorkerRegistry** abstraction as the basis for Cluster V2, including a local worker descriptor for the current node.
- Extended the job and job history models to carry a `worker_id`, preparing the system for worker-aware scheduling and diagnostics without changing single-node behavior.
- Added tests and documentation to anchor future multi-node and cluster features on a stable, well-specified worker registry and job–worker association model.
