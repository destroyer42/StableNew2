# PR-PERF-206A - Preview Reuse and Queue Submit Batching

Status: Completed 2026-03-18

## Summary

This PR removes two avoidable costs from the add-to-queue path:

- queue submission no longer rebuilds preview NJRs when cached preview records
  already exist
- multi-job preview submission now coalesces queue-updated emission into a
  single batch update instead of rebuilding the full queue summary once per job

## Runtime Changes

### 1. Reuse existing preview records when enqueueing

[pipeline_controller.py](/c:/Users/rob/projects/StableNew/src/controller/pipeline_controller.py)
now prefers `AppState.preview_jobs` inside `enqueue_draft_jobs(...)` and passes
those records directly into `submit_preview_jobs_to_queue(...)`.

That removes one full preview rebuild from the common:

`Add to Job -> preview exists -> Add to Queue`

path.

After a successful enqueue, the draft is cleared and preview jobs are reset to
`[]` directly instead of forcing another rebuild pass.

### 2. Batch queue submission at the JobService seam

[job_service.py](/c:/Users/rob/projects/StableNew/src/controller/job_service.py)
now supports:

- `enqueue(..., emit_queue_updated=True)`
- `submit_job_with_run_mode(..., emit_queue_updated=True)`
- `submit_queued(..., emit_queue_updated=True)`
- `submit_jobs_with_run_mode(jobs, batch_queue_update=True)`

The new batch helper submits all jobs with per-job queue updates suppressed,
then emits one final queue-updated event.

### 3. Preview submission service uses batch submit

[pipeline_submission_service.py](/c:/Users/rob/projects/StableNew/src/controller/pipeline_submission_service.py)
now converts all preview NJRs to queue `Job` objects first, then uses
`submit_jobs_with_run_mode(...)` when available.

It preserves a compatibility fallback to per-job submission for tests or stubs
that do not provide the new batch helper.

## Verification

Passed:

- `pytest tests/controller/test_job_service_unit.py tests/controller/test_pipeline_preview_to_queue_v2.py tests/controller/test_app_controller_add_to_queue_v2.py -q`
- `python -m compileall src/controller/job_service.py src/controller/pipeline_submission_service.py src/controller/pipeline_controller.py tests/controller/test_job_service_unit.py tests/controller/test_pipeline_preview_to_queue_v2.py tests/controller/test_app_controller_add_to_queue_v2.py`

## Follow-On

This PR removes redundant rebuilds and queue event churn. It does not yet speed
up prompt-pack parsing/config resolution or preview rebuild cadence. Those are
handled in:

- `PR-PERF-206B`
- `PR-PERF-206C`
