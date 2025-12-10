PR-0114B – Preview → Queue Submission Path (Queue-First).md
Intent

Make the “Add to Queue” button in PreviewPanelV2 submit real jobs through PipelineController → JobService → JobQueue, using NormalizedJobRecord as the single source of truth, instead of the legacy _build_job_from_draft path that Codex described as “stopping at the draft layer.”

Risk Tier: Tier 2 (controller + queue bridge, no runner changes).

Subsystems / Files

Controllers

src/controller/app_controller.py

on_add_job_to_queue_v2

Legacy on_add_job_to_queue / _build_job_from_draft (we’ll demote/bridge, not delete).

src/controller/pipeline_controller.py

get_preview_jobs

_build_normalized_jobs_from_state

Any new submit_jobs_to_queue-style helper.

Queue Orchestration

src/controller/job_service.py

submit_job_with_run_mode

submit_queued

Any helper we add for “queue-first from GUI” jobs.

GUI

src/gui/preview_panel_v2.py

_on_add_to_queue (already calls on_add_job_to_queue_v2).

Tests

tests/controller/test_app_controller_add_to_queue_v2.py

tests/gui_v2/test_pipeline_run_controls_v2_add_to_queue_button.py

tests/gui_v2/test_pipeline_run_controls_v2_pr203.py

New:

tests/controller/test_pipeline_preview_to_queue_v2.py

Key Changes

Define a single “preview jobs → queue” entrypoint on PipelineController

In PipelineController, add something like:

def submit_preview_jobs_to_queue(
    self,
    *,
    source: str = "gui",
    prompt_source: str = "pack",
) -> int:
    """
    Convert current preview jobs into queue jobs and submit them.

    Returns:
        Number of jobs successfully submitted.
    """
    normalized_jobs = self.get_preview_jobs()
    if not normalized_jobs:
        return 0

    submitted = 0
    for record in normalized_jobs:
        job = self._to_queue_job(
            record,
            run_mode="queue",
            source=source,
            prompt_source=prompt_source,
            prompt_pack_id=record.prompt_pack_id if hasattr(record, "prompt_pack_id") else None,
        )
        job.payload = lambda j=job: self._run_job(j)
        self._job_service.submit_job_with_run_mode(job)
        submitted += 1
    return submitted


This uses the same NormalizedJobRecord → Job adapter as the run buttons, so we’re not inventing another path.

Rewire AppController.on_add_job_to_queue_v2 to prefer the PipelineController path

In AppController.on_add_job_to_queue_v2:

First, try to use the pipeline controller path:

pipeline_ctrl = getattr(self, "pipeline_controller", None)
if pipeline_ctrl and hasattr(pipeline_ctrl, "submit_preview_jobs_to_queue"):
    try:
        count = pipeline_ctrl.submit_preview_jobs_to_queue(
            source="gui",
            prompt_source="pack"  # given this path comes from packs
        )
        if count > 0:
            self._append_log(f"[controller] Submitted {count} job(s) from preview to queue")
            return
    except Exception as exc:
        self._append_log(f"[controller] submit_preview_jobs_to_queue error: {exc!r}")


Only if that fails, fall back to the legacy handler chain:

handler_names = ("on_add_job_to_queue", "on_add_to_queue")
# …existing loop as today…


This fulfills Codex’s complaint: we now route through the normalized preview pipeline first.

Retain (but de-emphasize) _build_job_from_draft

Keep _build_job_from_draft and on_add_job_to_queue for backwards compatibility and older tests, but mark them as legacy in docstrings.

Add a short comment that the canonical path is now PipelineController.submit_preview_jobs_to_queue.

Ensure PreviewPanelV2._update_action_states is driven solely by job_draft

This is mostly already true, but confirm:

If job_draft.packs is non-empty → add_to_queue_button enabled.

We do not depend on normalized jobs to enable the button; that runs asynchronously via controller.

Tests

New tests/controller/test_pipeline_preview_to_queue_v2.py:

Provide a fake PipelineController with get_preview_jobs returning one or more NormalizedJobRecords.

Spy on JobService.submit_job_with_run_mode.

Call AppController.on_add_job_to_queue_v2.

Assert that submit_job_with_run_mode is called with run_mode="queue" and the expected number of jobs.

Update tests/controller/test_app_controller_add_to_queue_v2.py:

Add coverage for the new submit_preview_jobs_to_queue path.

Keep coverage for fallback behavior to legacy handler.

Update GUI tests for preview panel:

In tests/gui_v2/test_pipeline_run_controls_v2_add_to_queue_button.py, assert that clicking “Add to Queue” with a populated draft leads to AppController.on_add_job_to_queue_v2 being invoked and that the controller calls into PipelineController.submit_preview_jobs_to_queue (using mocks).

Docs / Changelog

Docs

docs/ARCHITECTURE_v2.5.md: Under “Queue / JobService,” add a sub-section describing “Preview jobs → JobService” using NormalizedJobRecord and submit_preview_jobs_to_queue.

docs/StableNew_Coding_and_Testing_v2.5.md: Add a note under “Queue tests” explaining the new preferred path for GUI queue submissions.

CHANGELOG.md

Entry for PR-0114B: “Preview ‘Add to Queue’ now submits jobs through PipelineController → JobService using normalized job records.”