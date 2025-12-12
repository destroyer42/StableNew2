Timestamp: 2025-11-22 16:32 (UTC-06)
PR Id: PR-#35-QUEUE-V2-JobQueueAndRunnerFoundation-001
Spec Path: docs/pr_templates/PR-#35-QUEUE-V2-JobQueueAndRunnerFoundation-001.md

# Title: Queue V2 – Job Model, JobQueue, and SingleNodeJobRunner Foundation

1. Summary

This PR formalizes and documents the queue foundation that Codex already implemented:
- Job model with priority ordering.
- Thread-safe in-memory JobQueue.
- SingleNodeJobRunner that executes jobs through a provided callable (pipeline entrypoint).
- Full test coverage for ordering, submission, status transitions, and loopback execution.

This PR records the spec, intent, boundaries, and architecture alignment so it may be moved into PriorWork_complete and tracked as PR-#35.

2. Problem Statement

StableNew V2’s Cluster Vision defines:
- Multi-node execution.
- Queue-based orchestration.
- Prioritized scheduling.
- Distributed workload dispatch.

Before this implementation:
- Pipeline runs were strictly synchronous + GUI-bound.
- No queuing semantics existed.
- No status transitions, job abstraction, or queue manager existed.
Codex implemented the foundational structure; this PR documents that work and locks in the architecture.

3. Goals

- Define Job model: id, payload (PipelineConfig), priority, status transitions, timestamps.
- Implement thread-safe JobQueue with:
  - Priority + FIFO ordering.
  - Safe push/pop.
  - Job lookup/update.
- Implement SingleNodeJobRunner:
  - Pulls jobs.
  - Executes via injected callable.
  - Updates status (queued → running → completed/failed).
  - Supports graceful shutdown.
- Add complete tests for job ordering, queue concurrency behavior, and runner correctness.

4. Scope: Allowed Files

queue/
  - job_model.py
  - job_queue.py
  - single_node_runner.py

tests/
  - tests/queue/test_job_model.py
  - tests/queue/test_job_queue_basic.py
  - tests/queue/test_single_node_runner_loopback.py

docs/
  - docs/Cluster_Compute_Vision_v2.md (append entry)
  - docs/Testing_Strategy_v2.md (append entry)
  - docs/CHANGELOG.md (append entry)

5. Forbidden Files

Do NOT modify:
- pipeline/**
- gui/**
- controller/**
- learning/**
- randomizer/**
- api/**
- gui_v1 legacy

6. Architecture Summary

6.1 Job Model
- Fields: job_id, payload, priority, status, created_at, started_at, completed_at, error.
- Status Enum: QUEUED, RUNNING, COMPLETED, FAILED, CANCELLED.
- Serializes cleanly to dict.
- Tests verify:
  - Status transitions.
  - Priority ordering.

6.2 JobQueue (Thread-Safe)
- Internal structure: heapq + dict lookup.
- Operations:
  - submit(job)
  - get_next_job()
  - update_job_status(job_id, status)
  - list_jobs(filter?)
- Concurrency:
  - Uses a Lock for all mutations.
- Tests verify:
  - Priority > FIFO ordering.
  - Safe multi-submit.
  - Job retrieval correctness.

6.3 SingleNodeJobRunner
- Takes:
  - JobQueue reference
  - Execution function (fn(job.payload) -> result)
- Loopback:
  - Poll queue
  - Run job
  - Update status
- Tests verify:
  - Loopback behavior.
  - Status transitions.
  - Failures captured.

7. Required Tests

- test_job_model.py
- test_job_queue_basic.py
- test_single_node_runner_loopback.py
- Full:
  - pytest tests/queue -v
  - pytest -v

8. Acceptance Criteria

- Queue foundation present & tested.
- Runner runs jobs through fn.
- Job priority ordering correct.
- Thread-safe queue operations confirmed.

9. Rollback Plan

- Remove queue folder.
- Remove queue tests.
- Roll back doc updates.
