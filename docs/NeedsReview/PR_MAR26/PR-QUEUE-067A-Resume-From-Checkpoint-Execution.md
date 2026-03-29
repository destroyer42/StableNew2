# PR-QUEUE-067A: Resume-From-Checkpoint Execution

## Goal

Pull forward the checkpoint substrate from `PR-QUEUE-067` into real execution behavior so queue-backed runs can resume from the last completed stage after crash-classified retry paths or manual return-to-queue cycles.

## Scope

### Runtime
- `src/pipeline/replay_engine.py`
- `src/pipeline/pipeline_runner.py`
- `src/controller/job_execution_controller.py`
- `src/queue/single_node_runner.py`

### Tests
- `tests/controller/test_pipeline_controller_queue_mode.py`
- `tests/controller/test_job_execution_controller_queue_v2.py`
- `tests/pipeline/test_replay_run_plan_v2.py`
- `tests/pipeline/test_job_queue_persistence_v2.py`

## Implementation

1. `ReplayEngine.replay_njr()` now accepts the live queue `Job` and derives a resumed NJR from the last valid stage checkpoint by using the existing reprocess contract:
   - `input_image_paths = last_checkpoint.output_paths`
   - `start_stage = next stage after the completed checkpoint`
2. `PipelineRunner.run_njr()` now emits stage checkpoints after each successful stage when a queue callback is present.
3. Queue-backed runner calls now re-raise crash-like WebUI failures instead of collapsing them into a dead-end `success=False` result, so the existing queue retry loop can restart WebUI and replay from checkpoint.
4. `JobExecutionController` now preserves diagnostics on wrapped replay failures and persists/restores execution metadata, including stage checkpoints, in queue snapshot metadata.
5. `SingleNodeJobRunner` now merges live checkpoint state with canonical-result checkpoint extraction instead of overwriting richer checkpoint data.

## Queue-Mode Test Cleanup

`tests/controller/test_pipeline_controller_queue_mode.py` was stale against the current controller contract:
- canonical preview submission now goes through `JobService.submit_job_with_run_mode()`
- the old fake `JobExecutionController.submit_pipeline_run()` path is no longer used
- the previous test harness leaked real runner state and could hang pytest

The test now stubs:
- a real preview NJR
- a fake `JobService`
- the controller status callbacks that still belong to `_job_controller`

## Verification

- `pytest tests/controller/test_pipeline_controller_queue_mode.py tests/controller/test_job_execution_controller_queue_v2.py tests/pipeline/test_replay_run_plan_v2.py tests/pipeline/test_job_queue_persistence_v2.py tests/queue/test_single_node_runner_webui_retry.py -q`
- `pytest --collect-only -q`
- `python -m compileall src/pipeline/replay_engine.py src/pipeline/pipeline_runner.py src/controller/job_execution_controller.py src/queue/single_node_runner.py tests/controller/test_pipeline_controller_queue_mode.py tests/controller/test_job_execution_controller_queue_v2.py tests/pipeline/test_replay_run_plan_v2.py tests/pipeline/test_job_queue_persistence_v2.py`

## Notes

- This PR makes checkpoint resume real for queue retries and queued-job persistence.
- It does not yet persist in-flight running jobs across full application shutdown; that remains a separate queue persistence extension.
