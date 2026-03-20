#CANONICAL
# Cluster_Compute_Spec_v2.5.md

---

# Executive Summary (8–10 lines)

The StableNew v2.5 Cluster Compute System enables multi-node, distributed execution of pipeline jobs while preserving the existing pipeline semantics, job lifecycle, and user experience.  
Jobs are still built deterministically on the main controller machine, but may be dispatched for execution to remote worker nodes with GPUs.  
Cluster compute introduces a new subsystem: **Cluster Orchestrator**, which manages workers, distributes jobs, retrieves results, and reports back completion events.  
Remote workers perform deterministic, isolated inference using the same pipeline runner used on the host machine.  
The architecture is designed to support heterogenous nodes, variable GPU capabilities, caching, load balancing, failure recovery, and future autoscaling.  
This subsystem forms Phase 3 of the StableNew Roadmap.  

---

# PR-Relevant Facts (Quick Reference)

- Cluster compute is **optional** and must not disrupt single-node execution.  
- Job construction **never happens on workers**; always on the main node.  
- Workers receive a fully resolved **NormalizedJobRecord** + asset URLs.  
- Cluster Orchestrator manages worker registration, health, scheduling, retries.  
- All communication uses a stable, versioned RPC protocol.  
- Worker nodes run a `WorkerRuntimeV2` that executes pipeline jobs headlessly.  
- Learning System still records results on the main node only.  
- Results flow: Worker → Orchestrator → Main Node → JobService → LearningWriter.  

---

============================================================
# 0. TLDR / BLUF — How Cluster Compute Works
============================================================

Main Node (User GUI + Controller + Job Builder)
↓ builds NormalizedJobRecord list
Cluster Orchestrator
↓ dispatches jobs to
Remote GPU Workers
↓ run pipeline stages headlessly
↓ return images + metadata
Orchestrator
↓ forwards completion event to
JobService + LearningWriter + UI

markdown
Copy code

### BLUF constraints:

- Deterministic job construction remains central and local.  
- Workers run the same pipeline execution stack, not a reduced version.  
- File/data transfer is explicit via orchestrator channels.  
- If cluster is disabled, everything behaves exactly as v2.5 single-node mode.

---

============================================================
# 1. Purpose and Non-Goals
============================================================

### 1.1 Purpose

Define the distributed compute architecture for:

- Worker discovery & registration  
- Job dispatch, scheduling, and execution  
- Results retrieval and failure handling  
- Version negotiation and capability signaling  
- Asset synchronization (models, LORAs, prompt packs)  
- Integration with JobService, pipeline runner, and UI  

### 1.2 Non-Goals

Cluster Compute must **not**:

- Change or override JobBuilder logic  
- Perform randomization or mutation on workers  
- Modify pipeline configuration  
- Change pipeline stage semantics  
- Execute GUI or controller logic on workers  
- Replace or modify the Learning System  

Cluster compute deals exclusively with **distributed execution**, not job creation.

---

============================================================
# 2. Cluster Architecture Overview
============================================================

### 2.1 Roles

#### **Main Node**
- Hosts GUI, controllers, JobService, Cluster Orchestrator  
- Builds NormalizedJobRecord list  
- Stores queue, learning data, history  
- Decides which jobs run where  
- Displays progress across workers  

#### **Worker Nodes**
- Run a WorkerRuntimeV2 instance  
- Execute assigned jobs  
- Host local copy of models or fetch them from shared store  
- Return outputs to orchestrator  
- Use consistent StableNew runner implementation  

#### **Cluster Orchestrator**
- Maintains worker registry  
- Schedules jobs  
- Handles load balancing & retries  
- Monitors worker health  
- Provides a stable API for worker communication  

---

============================================================
# 3. Orchestrator Design
============================================================

### 3.1 Canonical Module

src/cluster/orchestrator_v2.py

css
Copy code

### 3.2 Responsibilities

- Worker registration & capability handshake  
- Maintain a WorkerState table  
- Maintain WorkQueue separate from local JobService queue  
- Dispatch NormalizedJobRecord objects to workers  
- Track in-flight jobs  
- Retry failed jobs (configurable)  
- Return job completion events to JobService  

### 3.3 Worker Registration Protocol

Workers must report:

```json
{
  "worker_id": "string",
  "gpu_name": "string",
  "vram_gb": 16,
  "max_batch": 4,
  "supported_models": ["sdxl_1.0", "sdxl_refiner_1.0"],
  "software_version": "2.5.0",
  "runner_protocol": "1"
}
Orchestrator must:

Reject workers with incompatible versions

Maintain compatibility mapping in future versions

3.4 Scheduling Strategy
Initial version uses greedy scheduling:

Idle worker → assign next job

Prefer worker with compatible model cached locally

Prefer worker that recently executed same model

Future extensions:

Weighted scheduling

VRAM-aware assignment

Multi-job batches

Worker priority rules

3.5 Fault Handling
If worker disconnects:

Mark in-flight job as failed

Requeue job

If job fails:

Retry N times (configurable)

If repeated failure:

Mark job as “failed” and continue

============================================================

4. WorkerRuntimeV2
============================================================

4.1 Canonical Module
bash
Copy code
src/cluster/worker_runtime_v2.py
4.2 Responsibilities
Receive job payload

Download or confirm model/asset availability

Execute full pipeline (runner_v2) headlessly

Save outputs to worker local disk

Return:

image bytes (or URLs if using shared store)

metrics

runtime data

any warnings

4.3 Forbidden Actions
Workers must not:

Generate variants

Modify configs

Modify seeds

Bypass or reorder pipeline stages

Change JobIDs

Talk directly to GUI or JobService

4.4 Required Behavior
Workers must:

Execute pipeline deterministically

Report all errors with stable codes

Emit stage-level runtime metrics

Support cancellation requests

============================================================

5. Data Transfer & Asset Management
============================================================

Architecture supports three asset strategies:

5.1 Strategy A — Shared Filesystem (NAS/NFS/SMB)
Workers mount same model directory

Orchestrator only sends metadata

Easiest for home-lab clusters

5.2 Strategy B — HTTP / Tailscale Sync
Workers fetch only missing models

Cached models stored locally

Good for mixed environments

5.3 Strategy C — Blob Store
Models stored in object storage

Workers pull via pre-signed URLs

Enables distributed cloud/hybrid clusters

Initial v2.5 implementation supports Strategy A, with Strategy B planned for v2.6.

============================================================

6. RPC Protocol (Cluster Transport Layer)
============================================================

6.1 Transport Options
Canonical initial transport:

javascript
Copy code
WebSocket or HTTP POST JSON
Worker connections form long-lived channels.

6.2 Message Types
WorkerRegister
Worker → Orchestrator

JobDispatch
Orchestrator → Worker
Payload includes normalized job config + paths.

JobStarted
Worker → Orchestrator

JobProgress
Worker → Orchestrator
(Optional stage progress reporting)

JobCompleted
Worker → Orchestrator
Contains:

output file URLs or binary

runtime metrics

warnings if any

JobFailed
Worker → Orchestrator

WorkerHeartbeat
Worker → Orchestrator

============================================================

7. Job Lifecycle (Distributed)
============================================================

7.1 Job Construction (always local)
ini
Copy code
MergedConfig = ConfigMergerV2(...)
Variants = RandomizerEngineV2(...)
NormalizedJobs = JobBuilderV2(...)
7.2 Job Routing
Main node:

nginx
Copy code
NormalizedJobRecord → Orchestrator → WorkerRuntimeV2
Worker:

nginx
Copy code
WorkerRuntimeV2 → results → Orchestrator → JobService + LearningWriterV2
7.3 Failure Modes
Worker crash → retry

Orchestrator crash → pending jobs rehydrated from journal

Network issues → temporary retry

Runner errors → fail job, record metrics

============================================================

8. UI Requirements (User-Facing)
============================================================

8.1 Cluster Dashboard (optional)
GUI may include:

Worker list

Worker health

Job distribution map

Throughput metrics

Model caching status

8.2 Queue/Preview Semantics
No changes are required to PreviewPanel or QueuePanel.
Jobs appear as single entries regardless of execution location.

8.3 Worker Selection (optional future)
User may choose:

Auto (default)

Specific worker

Local-only mode

============================================================

9. Testing Requirements
============================================================

9.1 Unit Tests
Workers:

Test job execution with stub runner

Test error codes, cancellation, retries

Orchestrator:

Worker registration

Job scheduling decisions

Disconnection and retry logic

9.2 Integration Tests
Simulated cluster:

Two workers + orchestrator + stub runner

Jobs distributed correctly

Failures routed correctly

Completion results forwarded properly

9.3 End-to-End Tests (Phase 3B)
Cluster enabled → queue behaves identically to local mode

User sees identical preview + history regardless of worker location

Learning System logs correctly on main node

============================================================

10. Security Considerations
============================================================

Worker auth via shared secret or Tailscale identity

Protocol versioning to prevent incompatible worker nodes

Sandbox model execution on worker

Prevent arbitrary code execution

============================================================

11. Future Extensions (v2.6+)
============================================================

Planned additions:

Worker autoscaling

Model prefetching and warm pools

Distributed caching layers

Performance dashboards

Worker classes (high-memory, low-latency, CPU-only)

Multi-job batches per worker

Pipeline parallelism (experimental)

Extensions must preserve:

Deterministic job definition

Stability of main-node job creation

Non-invasive cluster behavior

============================================================

12. Deprecated Behaviors (Archived)
============================================================
#ARCHIVED
(Do not implement; preserved only for historical clarity.)

Deprecated:

Workers modifying configs

Legacy V1-style SSH command runners

Direct GUI-to-worker communication

Per-worker randomization or seed mutation

File-sharing assumptions baked into pipeline code

End of Cluster_Compute_Spec_v2.5.md