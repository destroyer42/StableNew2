# PR-OBS-249A - Structured Event Logging Contract and Ascii Normalization

Status: Completed 2026-03-21

## Summary

This PR established the structured logging contract for the active execution
path and removed the touched emoji/glyph log markers from runtime surfaces.

## Delivered

- canonical message normalization and repeat-aware handler metadata in
  `src/utils/logger.py`
- structured/debug-friendly logging cleanup in:
  - `src/api/client.py`
  - `src/pipeline/executor.py`
  - `src/pipeline/pipeline_runner.py`
  - `src/queue/single_node_runner.py`
  - `src/controller/job_service.py`
- clearer `INFO` vs `DEBUG` semantics for the active execution path

## Tests

- `pytest tests/utils/test_inmemory_log_handler.py tests/utils/test_logger_integration.py tests/test_api_client.py tests/api/test_webui_api_upscale_payload.py tests/pipeline/test_executor_adetailer.py tests/pipeline/test_executor_refinement_manifest.py tests/pipeline/test_pipeline_runner.py -q`
- result: `63 passed`
