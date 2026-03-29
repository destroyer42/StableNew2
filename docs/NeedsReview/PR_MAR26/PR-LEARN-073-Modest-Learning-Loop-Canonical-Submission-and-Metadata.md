# PR-LEARN-073: Modest Learning Loop Completion

## Objective

Complete the learning loop modestly by removing the remaining non-canonical learning submission path and improving learning-job reproducibility metadata without introducing closed-loop automation.

## Scope

- Route learning variant submission through canonical `JobService.enqueue_njrs()`.
- Remove learning-specific queue `Job` fabrication and payload shims.
- Ensure learning NJRs carry the merged config and explicit learning provenance.
- Keep learning completion routing and recommendation flows working on the canonical artifact contract.

## Files Changed

- `src/learning/execution_controller.py`
- `src/gui/controllers/learning_controller.py`
- `tests/controller/test_learning_controller_njr.py`
- `tests/controller/test_learning_controller_integration.py`
- `tests/controller/test_learning_completion_resume_regressions.py`
- `tests/learning_v2/test_phase2_job_completion_integration.py`

## Implementation

### 1. Canonical learning submission

`src/learning/execution_controller.py`

- Replaced manual queue `Job(...)` construction with `JobService.enqueue_njrs([record], run_request)`.
- Added a bounded learning `PipelineRunRequest` builder for single-variant queue submission.
- Preserved `job_id -> variant` and `job_id -> context` tracking for completion/failure callbacks.
- Removed the obsolete placeholder execution path that fabricated `Job.payload` wrappers.

### 2. Learning controller cleanup

`src/gui/controllers/learning_controller.py`

- Auto-creates a `LearningExecutionController` from the canonical pipeline `JobService` when available.
- Removes compatibility submission fallbacks that used `queue_controller.submit_pack_job()` or `submit_job_with_run_mode()` directly.
- Removes `_njr_to_queue_job()` and `_execute_learning_job()`.
- Upgrades txt2img learning NJRs to preserve:
  - merged `config`
  - `path_output_dir`
  - `filename_template`
  - `prompt_pack_name`
  - `variant_index` / `variant_total`
  - explicit `submission_source="learning"`
  - nested `extra_metadata["learning"]` provenance block
- Keeps non-txt2img learning runs on the canonical reprocess builder path, now stamped with learning source/provenance.
- Relaxes constructor rigidity so passive learning/result-routing use cases do not require a pipeline controller at construction time.

### 3. Test alignment

- Rewrote learning submission tests to assert `enqueue_njrs()` instead of direct queue `Job` submission.
- Added a direct execution-controller regression proving learning submission uses canonical NJR queue entry.
- Updated stale Phase 2 learning assertions so `completed_images` reflects actual linked image count instead of one-per-job.

## Verification

- `pytest tests/controller/test_learning_controller_njr.py tests/controller/test_learning_controller_integration.py tests/controller/test_learning_completion_resume_regressions.py tests/learning_v2/test_phase2_job_completion_integration.py tests/controller/test_learning_run_summary.py tests/controller/test_learning_controller_resume_state.py tests/controller/test_learning_controller_review_feedback.py tests/controller/test_learning_controller_review_feedback_undo.py tests/integration/test_learning_review_recommendation_e2e.py -q`
- `pytest --collect-only -q`
- `python -m compileall src/learning/execution_controller.py src/gui/controllers/learning_controller.py tests/controller/test_learning_controller_njr.py tests/controller/test_learning_controller_integration.py tests/controller/test_learning_completion_resume_regressions.py tests/learning_v2/test_phase2_job_completion_integration.py`

## Outcome

Learning experiment submission is now aligned with the same NJR-only queue path used by the rest of the system. The learning loop remains modest: stronger metadata, reproducible queue submission, and preserved recommendation/review behavior, without introducing autonomous execution logic.
