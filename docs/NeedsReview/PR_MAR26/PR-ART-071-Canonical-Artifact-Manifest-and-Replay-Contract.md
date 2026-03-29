# PR-ART-071: Canonical Artifact, Manifest, and Replay Contract

## Goal

Define one canonical runtime artifact contract for pipeline results, stage manifests, and downstream consumers so replay, history, learning, and diagnostics stop guessing between `path`, `output_path`, `all_paths`, `video_path`, and stage-specific result shapes.

## Scope

- `src/pipeline/artifact_contract.py`
- `src/pipeline/pipeline_runner.py`
- `src/pipeline/executor.py`
- `src/utils/image_metadata.py`
- `src/learning/execution_controller.py`
- `src/learning/output_scanner.py`
- `src/controller/job_history_service.py`
- targeted pipeline/history/learning tests

## Changes

1. Added `src/pipeline/artifact_contract.py` with the canonical `stablenew.artifact.v2.6` record shape plus helpers for:
   - artifact-type inference
   - result/variant normalization
   - artifact-path extraction
   - manifest artifact payload creation
2. `PipelineRunner` now canonicalizes `PipelineRunResult.variants` and `run_metadata.stage_outputs` through the same helper.
3. Still-image stage manifests and video stage metadata now include an `artifact` block with:
   - `schema`
   - `stage`
   - `artifact_type`
   - `primary_path`
   - `output_paths`
   - `manifest_path`
   - `thumbnail_path`
   - `input_image_path`
4. Embedded image metadata payloads now include the same canonical artifact block.
5. Learning and history consumers now extract artifact paths from the canonical contract first, then fall back to older keys.

## Result

The durable artifact contract is now consistent across:

- `PipelineRunResult.variants`
- `run_metadata.json` stage outputs
- still-image embedded metadata payloads
- stage manifests written by executor paths
- learning execution path extraction
- history sidecar reconciliation

This PR preserves older top-level keys for compatibility, but the canonical contract is now the `artifact` block.

## Verification

- `pytest tests/pipeline/test_artifact_contract.py tests/pipeline/test_pipeline_result_state.py tests/pipeline/test_pipeline_runner.py tests/pipeline/test_svd_runtime.py tests/history/test_history_image_metadata_reconcile.py tests/learning_v2/test_output_scanner.py -q`
- `pytest tests/pipeline/test_executor_prompt_optimizer.py tests/pipeline/test_pipeline_runner_variants.py tests/history/test_history_replay_integration.py tests/controller/test_job_execution_controller_queue_v2.py tests/controller/test_app_controller_photo_optimize.py -q`
- `pytest --collect-only -q`
- `python -m compileall src/pipeline/artifact_contract.py src/pipeline/pipeline_runner.py src/pipeline/executor.py src/utils/image_metadata.py src/learning/execution_controller.py src/learning/output_scanner.py src/controller/job_history_service.py`
