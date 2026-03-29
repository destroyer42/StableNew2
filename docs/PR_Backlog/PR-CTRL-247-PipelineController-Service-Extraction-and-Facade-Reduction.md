# PR-CTRL-247 - PipelineController Service Extraction and Facade Reduction

Status: Specification
Priority: HIGH
Date: 2026-03-29

## Scope

- continue reducing `PipelineController` after the earlier history handoff extraction
- move normalized queue-submission orchestration into a dedicated service
- leave `PipelineController` as the facade that wires services and owns controller-level policy

## Delivered Slice

- added `src/controller/pipeline_controller_services/queue_submission_service.py`
- moved queueable-record filtering, prompt-pack metadata normalization, model/VAE grouping, and batch queue submission orchestration behind that service
- kept controller public methods stable by delegating through the service

## Validation

- `pytest tests/controller/test_queue_submission_service.py tests/controller/test_pipeline_controller_learning_queue_cap.py tests/controller/test_pipeline_preview_to_queue_v2.py -q`

