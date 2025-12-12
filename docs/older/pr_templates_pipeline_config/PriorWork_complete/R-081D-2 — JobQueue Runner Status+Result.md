PR-081D-2 — JobQueue / Runner Status+Result Contract Alignment

Intent
Fix the TypeError: JobQueue._record_status() got an unexpected keyword argument 'result' failures by updating the JobQueue internal contract to accept a result field (as tests expect) and propagate it through job history.

This restores compatibility with current queue tests and job-runner integration, without altering the runner core logic.

Summary of Failures Addressed

Repeated stack traces from:

TypeError: JobQueue._record_status() got an unexpected keyword argument 'result'


Occurs in:

tests/queue/test_job_queue_basic.py

tests/queue/test_single_node_runner_loopback.py

tests/queue/test_jobrunner_integration.py

tests/controller/test_job_history_service.py

Root Cause:
The job runner and tests expect:

self._record_status(job_id, status, ts, result=result)


but _record_status() signature no longer accepts result.

Scope & Risk Level

Risk: Medium

Subsystem: Queue system only

No changes to pipeline executor, GUI, or controller.

Allowed Files to Modify
src/queue/job_queue.py
src/queue/job_history_store.py
src/queue/job_model.py   (if required to store 'result')
tests/queue/*.py
tests/controller/test_job_history_service.py

Forbidden Files
src/pipeline/*
src/gui/*
src/controller/*
src/main.py

Implementation Plan
1. Update JobQueue._record_status() signature

Add:

def _record_status(self, job_id, status, ts, error_message=None, result=None):
    ...

2. Persist result in JobHistoryStore

On write, store result as a JSON-serializable blob.

Keep backward compatibility (result may be None).

3. Update JobQueue transitions to pass result

Transitions using:

self._update_status(job_id, JobStatus.COMPLETED, result=job_result)


must be accepted and forwarded.

4. Update JobModel / history entry format (if required)

Ensure the history entry is shaped like:

{
  "status": "COMPLETED",
  "timestamp": ts,
  "error": None,
  "result": <whatever-executor-returned>
}

5. Update tests expecting result passthrough

Tests expecting:

history.last().result == some_value


must work.

6. Ensure queue/runner threads do not break

Runner calls:

self.job_queue.mark_running(job_id)
self.job_queue.mark_completed(job_id, result=...)


must pass through cleanly.

7. Validate JobHistoryService merging

active + history merge must include results.

Acceptance Criteria
✔ All queue tests pass:

test_job_queue_basic.py

test_single_node_runner_loopback.py

test_jobrunner_integration.py

✔ Controller job-history tests pass:

test_job_history_service_merges_active_and_history

test_job_history_service_cancel_and_retry

✔ _record_status() accepts result without error
✔ All queue history entries include the result field
✔ Runner thread no longer throws unhandled TypeErrors
✔ No changes to pipeline, controller, or GUI subsystems
Validation Checklist (StableNewV2 PR Guardrails)

JobQueue changes contained

JobRunner remains stable

JobHistory persists expected fields

Thread-safety unchanged

Test-only modifications to expected values are allowed

No modification to forbidden files

🚀 Deliverable Output

Updated JobQueue contract

Updated JobHistoryStore persistence

Updated queue tests and controller history tests

Full green for all queue and history tests