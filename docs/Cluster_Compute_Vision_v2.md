# Cluster Compute Vision v2  
_Queue‑Managed, GPU‑Aware Orchestration (C3)_

---

## 1. Objective

Transform StableNew from a single‑machine GUI into a **central controller** capable of:

- Dispatching jobs to multiple Windows/Linux nodes on a home LAN.
- Taking advantage of different GPUs (VRAM, performance) across machines.
- Running overnight batches of randomized variants for later review.
- Feeding LearningRecords from all nodes back into a single learning corpus.

The target environment is a **home lab / personal cluster**, not a multi‑tenant cloud service.

---

## 2. Roles and Components

- **Controller Node (StableNew Core)**
  - Runs the GUI and queue manager.
  - Holds the authoritative config, learning records, and job history.
  - Job history is persisted via the JobHistoryStore abstraction so restarts do not wipe recent job visibility.
  - Schedules jobs to worker nodes based on capabilities and load.
  - Mediates GUI job actions (cancel/retry) and forwards them to queue/runner layers.
  - Maintains a WorkerRegistry with a local worker descriptor; future remote workers will extend this registry.

- **Worker Nodes**
  - Run SD WebUI (or equivalent backend) plus a **StableNew worker agent**.
  - Advertise available GPUs and performance hints.
  - Execute assigned jobs and report outputs back.

- **Shared Storage (optional but recommended)**
  - TrueNAS or similar, providing a shared dataset for:
    - Models, LoRAs, embeddings, VAE files.
    - Input prompt packs / configs.
    - Output images and logs (or at least a coordinated storage layout).

---

## 3. Job Model

A **Job** encapsulates:

- Job metadata
  - job_id
  - originating user (single‑user in this design, but still tracked)
  - priority (interactive vs batch)
  - timestamps

- Workload
  - PipelineConfig (or reference to a preset + overrides).
  - Learning metadata (is learning enabled? plan id?).
  - Randomizer metadata (variant index, plan reference).

- Execution parameters
  - Required capabilities (min VRAM, required models present).
  - Stage scope:
    - Full pipeline on one node.
    - Or specific stages (e.g., upscale only).

On completion, jobs yield:

- Success/failure state.
- Output references.
- Optional LearningRecord(s).

---

## 4. Queue Manager (C3 Core)

The queue manager lives inside the controller node and is responsible for:

- Accepting jobs from the GUI and/or CLI tools.
- Maintaining job queues per priority class:
  - Interactive queue (front of line).
  - Batch/overnight queue (background).
- Assigning jobs to workers based on:
  - GPU VRAM and capabilities.
  - Current load (active jobs, historical throughput).
  - Optional policies (e.g., certain nodes reserved for interactive work).

Optional but desirable:

- Persist queue state so the system can recover after a restart.
- Provide an inspection/debugging UI (“what is running where?”).

---

## 5. Worker Agents

Worker agents are lightweight processes that:

- Start up and **register** with the controller:
  - Node id / name.
  - GPUs: count, VRAM, approximate FLOPS.
  - Local paths for models and outputs.
- Maintain a heartbeat with the controller.
- Request jobs when ready and execute them by:
  - Invoking SD WebUI API on that machine.
  - Storing results to either local or shared storage.
  - Reporting job completion (with paths/URIs).

Failure handling:

- If a worker stops heartbeating, its in‑flight jobs are marked as failed or retried depending on policy.
- Unsafe jobs (e.g., incomplete outputs) should fail clearly with logs attached.

---

## 6. Scheduling Strategy (C3)

The scheduler is **capability + load aware**, with rules such as:

- Assign large, high‑resolution jobs (or multi‑variant runs) to nodes with the most VRAM.
- Keep at least one reasonably strong node available for interactive work.
- Spread batch jobs across nodes to maximize throughput.

Steps:

1. Controller ranks nodes for a job:
   - Filter out nodes that lack required VRAM or models.
   - Sort by a composite score of (free capacity, historical throughput, recency of use).

2. First feasible node gets the job.
3. Scheduler updates node state and job status.

In learning runs:

- Each LearningRunStep is treated as a job.
- Steps can be run in parallel across nodes, then aggregated back into a LearningRunResult.

---

## 7. Data & Storage Considerations

To avoid massive file copying:

- Prefer **shared storage** for models and outputs:
  - Worker nodes map network drives (via SMB, NFS, or similar).
  - StableNew uses consistent paths relative to a shared root.

- Alternatively, a “sync” model could be implemented later (e.g., syncing models to nodes as needed), but this is likely overkill for a home lab.

LearningRecords:

- Should be centrally written by the controller (LearningRecordWriter) even if workers emit intermediate data.
- A simple pattern:
  - Workers return metadata about runs (hashes, config fragments, image identifiers).
  - Controller synthesizes the final LearningRecord to avoid distributed writers.

---

## 8. Integration with GUI and UX

- GUI shows:
  - An indicator of how many nodes are currently connected.
  - Basic node stats (name, GPU, VRAM, status).
  - Queue summary (how many jobs pending, running, completed).

- For interactive runs:
  - User doesn’t need to care where the job executes.
  - Controller quietly chooses the best node under the hood.

- For batch / overnight runs:
  - GUI should communicate that jobs may run on multiple nodes.
  - Provide a way to inspect results by job id, prompt pack, or time window.

---

## 9. Testing Strategy

- **Unit tests** for scheduler decisions using fake nodes and jobs.
- **Simulation tests** for queue behavior under load (no real SD calls).
- Later **integration tests** for a single worker in loopback mode (controller + worker on the same machine) to validate end-to-end flows without involving multiple physical nodes.
- Initial queue/job skeleton (PR-QUEUE-V2-JOBMODEL-001) provides Job model, in-memory JobQueue, and SingleNodeJobRunner for single-node loopback; networking is still out of scope.

---

## 10. Non‑Goals

- No dynamic auto‑scaling of cloud instances.
- No complex SLAs or fairness for multiple users (single operator only).
- No automatic model distribution in v2; assume manual provisioning of models across nodes or shared storage.
