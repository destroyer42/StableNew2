# PR-REPROC-072: Productized Reprocess Subsystem

## Goal

Promote reprocess from a controller-local batch trick into a more canonical, validated subsystem:

- reprocess NJRs carry explicit provenance
- review/photo-optimize reprocess planning is centralized in pipeline code
- submissions use the canonical `JobService.enqueue_njrs()` path
- output collection uses the canonical artifact contract

## Implemented Scope

### 1. Reprocess planning moved closer to pipeline code

Updated [src/pipeline/reprocess_builder.py](../../src/pipeline/reprocess_builder.py):

- added `ReprocessSourceItem`
- added `ReprocessJobPlan`
- added `build_grouped_reprocess_jobs(...)`
- added `build_run_request(...)`
- added `extract_reprocess_output_paths(...)`
- added canonical reprocess provenance metadata:
  - `extra_metadata["reprocess"]["schema"] == "stablenew.reprocess.v2.6"`
  - `extra_metadata["reprocess"]["source"]`
  - `extra_metadata["reprocess"]["input_image_paths"]`
  - `extra_metadata["reprocess"]["requested_stages"]`
  - `extra_metadata["reprocess"]["source_items"]`

`build_reprocess_job(...)` now also stamps `prompt_source="reprocess"` on the NJR and preserves the older flat compatibility fields:

- `reprocess_mode`
- `original_image_count`
- `reprocess_stages`

### 2. AppController no longer fabricates queue jobs for reprocess

Updated [src/controller/app_controller.py](../../src/controller/app_controller.py):

- `on_reprocess_images()` now builds `ReprocessSourceItem`s and delegates grouping to `ReprocessJobBuilder`
- `on_reprocess_images_with_prompt_delta()` now builds reprocess items from metadata baselines and delegates grouping to `ReprocessJobBuilder`
- `on_optimize_photo_assets()` now uses the same grouped reprocess planner and only contributes photo-optimize-specific metadata/output-dir policy
- `_submit_reprocess_njrs()` now uses `JobService.enqueue_njrs()` plus a canonical `PipelineRunRequest`

This removes the controller-local `Job(...)` + callable payload reprocess execution path.

### 3. Queue/history snapshots preserve reprocess identity

Updated [src/controller/job_service.py](../../src/controller/job_service.py):

- `_job_from_njr()` now respects NJR/metadata-derived `prompt_source`
- `_job_from_njr()` now respects reprocess `submission_source`
- job snapshots are now built through `build_job_snapshot(...)` instead of raw `asdict(record)`

This keeps reprocess jobs from being mislabeled as pack jobs in the queue/history path.

### 4. Photo optimize output mapping now uses artifact semantics

Updated [src/controller/app_controller.py](../../src/controller/app_controller.py):

- `_extract_reprocess_output_paths()` now delegates to the shared reprocess helper
- artifact extraction prefers canonical `variant["artifact"]` output paths instead of stage-specific `path` guessing

## Tests

Updated:

- [tests/pipeline/test_reprocess_builder_defaults.py](../../tests/pipeline/test_reprocess_builder_defaults.py)
- [tests/controller/test_app_controller_reprocess_review_tab.py](../../tests/controller/test_app_controller_reprocess_review_tab.py)
- [tests/controller/test_app_controller_photo_optimize.py](../../tests/controller/test_app_controller_photo_optimize.py)
- [tests/controller/test_job_service_njr_validation.py](../../tests/controller/test_job_service_njr_validation.py)
- [tests/integration/test_learning_review_recommendation_e2e.py](../../tests/integration/test_learning_review_recommendation_e2e.py)

Also verified adjacent surfaces:

- [tests/controller/test_svd_controller.py](../../tests/controller/test_svd_controller.py)
- [tests/controller/test_pipeline_controller_queue_mode.py](../../tests/controller/test_pipeline_controller_queue_mode.py)
- [tests/pipeline/test_reprocess_batching.py](../../tests/pipeline/test_reprocess_batching.py)
- [tests/test_reprocess_batching.py](../../tests/test_reprocess_batching.py)

## Verification

Passed:

- `pytest tests/pipeline/test_reprocess_builder_defaults.py tests/controller/test_app_controller_reprocess_review_tab.py tests/controller/test_app_controller_photo_optimize.py tests/controller/test_job_service_njr_validation.py tests/integration/test_learning_review_recommendation_e2e.py -q`
- `pytest tests/controller/test_svd_controller.py tests/controller/test_pipeline_controller_queue_mode.py tests/pipeline/test_reprocess_batching.py tests/test_reprocess_batching.py -q`
- `pytest --collect-only -q` -> `2253 collected / 1 skipped`
- `python -m compileall src/pipeline/reprocess_builder.py src/controller/app_controller.py src/controller/job_service.py ...`

## Outcome

Reprocess is still intentionally built on top of the normal NJR -> queue -> replay/runner path, but it is no longer a controller-owned execution side path. It now has:

- canonical submission semantics
- explicit provenance
- artifact-aware output mapping
- shared planning for review and photo optimize workflows
