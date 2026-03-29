# PR-CTRL-247 - PipelineController Service Extraction and Facade Reduction

Status: Completed 2026-03-29

## Delivered

- queue-submission orchestration moved out of `PipelineController` and into `src/controller/pipeline_controller_services/queue_submission_service.py`
- `PipelineController` now delegates queueable-record filtering, prompt-pack metadata normalization, model/VAE grouping, and batch submission mechanics through that service
- controller-facing behavior stayed stable while reducing facade responsibility

## Validation

- `tests/controller/test_queue_submission_service.py`
- `tests/controller/test_pipeline_controller_learning_queue_cap.py`
- `tests/controller/test_pipeline_preview_to_queue_v2.py`
- `tests/controller/test_pipeline_controller_queue_mode.py`

