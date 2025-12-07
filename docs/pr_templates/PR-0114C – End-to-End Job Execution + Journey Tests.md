PR-0114C – End-to-End Job Execution + Journey Tests.md
Intent

Verify and harden the full path:

Add to Job → Preview → Add to Queue → JobQueue → SingleNodeJobRunner → PipelineRunner → Images + History.

This PR should not massively refactor pipeline execution; it should:

Ensure the Job.payload callable uses PipelineController._run_job (which wraps PipelineRunner).

Confirm JobService and SingleNodeJobRunner update queue + history correctly.

Add journey tests that exercise this full path (using mocks for SD WebUI).

Risk Tier: Tier 3 (queue/runner + integration tests).

Subsystems / Files

Queue + Runner

src/queue/job_model.py

src/queue/job_queue.py

src/queue/single_node_runner.py

Controller + Pipeline

src/controller/job_service.py (already bridges queue + runner)

src/controller/pipeline_controller.py

_run_job

Any run/submit helpers that attach the payload.

src/pipeline/pipeline_runner.py

Only to the extent needed to ensure runner.run(config, cancel_token) is used by _run_job.

History

src/controller/job_history_service.py

src/queue/job_history_store.py

Tests

tests/journeys/journey_helpers_v2.py

Existing journey tests that are supposed to cover preview→queue→run→history.

New:

tests/journeys/test_full_pack_to_image_pipeline_v2.py

Key Changes

Standardize how Job.payload is attached for GUI jobs

In PipelineController (reused by both “Run” and “Add to Queue”):

Ensure all GUI-origin jobs created from normalized jobs set:

job.payload = lambda j=job: self._run_job(j)


Confirm _run_job:

Invokes PipelineRunner via runner.run(job.pipeline_config, self.cancel_token) (for multi-stage path).

Returns a dict suitable to be stored in JobQueue.mark_completed(..., result=result).

This ensures that when SingleNodeJobRunner calls run_callable(job), it drives the multi-stage pipeline.

Verify JobService → SingleNodeJobRunner flow for queued jobs

In JobService.submit_queued and submit_direct:

Confirm both code paths ultimately:

job_queue.submit(job)

Kick SingleNodeJobRunner.start() when needed.

Use runner.run_once(job) in direct mode.

Ensure _emit_queue_updated and _set_queue_status correctly reflect:

QUEUED → RUNNING → COMPLETED (or FAILED/CANCELLED) transitions.

Minimal code changes here—ideally we just strengthen tests and fix any obvious status holes.

Confirm SingleNodeJobRunner marks jobs and notifies JobService properly

In single_node_runner.py:

Confirm the loop:

job = self.job_queue.get_next_job()
result = self.run_callable(job)
self.job_queue.mark_completed(job.job_id, result=result)
self._notify(job, JobStatus.COMPLETED)


Ensure _notify(job, status) is wired to the JobService listener so history + GUI updates fire.

We only change behavior if we find a status mismatch that breaks journey tests.

End-to-end journey test for pack → image

Add tests/journeys/test_full_pack_to_image_pipeline_v2.py:

Use the GUI harness in tests/journeys/journey_helpers_v2.py to:

Open the pipeline tab with pack sidebar.

Select a pack, click “Add to Job.”

Confirm preview shows a job summary.

Click “Add to Queue.”

Start the queue runner (if not auto-run).

Mock PipelineRunner or SDWebUIClient so that:

No real HTTP calls are made.

A fake result dict is returned with at least one “image path.”

Assert:

JobQueue.list_jobs(status_filter=COMPLETED) has at least one job.

JobHistoryStore has an entry for that job.

The history panel in GUI (if accessible through helpers) shows an entry with matching prompts / pack name.

Docs / Changelog

Docs

docs/ARCHITECTURE_v2.5.md: Update the Queue/Runner section with a short “Happy path: Pack → Preview → Queue → PipelineRunner” diagram and bullet list.

docs/StableNew_Coding_and_Testing_v2.5.md: Add a “Known Pitfalls for Queue Testing” subsection (codifying Codex’s earlier narrative) and reference the new journey test as the canonical end-to-end check.

CHANGELOG.md

Entry for PR-0114C: “End-to-end pack→queue→runner→history pipeline validated by new journey test; queue/runner status handling tightened.”