# PR-OBS-249A - Structured Event Logging Contract and Ascii Normalization

Status: Implemented 2026-03-21
Priority: HIGH
Effort: SMALL
Phase: Observability and Logging
Date: 2026-03-21

## Summary

Establish one StableNew-owned structured logging contract for the active runtime
path and remove emoji/glyph-based log markers from the touched execution
surfaces.

## Delivered

- added canonical message normalization and repeat-aware in-memory log support
  in `src/utils/logger.py`
- re-leveled noisy trace logs from `INFO` to `DEBUG` in the active API,
  executor, pipeline runner, queue runner, and job-service paths
- replaced touched emoji/glyph runtime log markers with ASCII event/channel
  labels
- kept Python `logging` plus `log_with_ctx(...)` as the single logging
  transport

## Key Files

- `src/utils/logger.py`
- `src/api/client.py`
- `src/pipeline/executor.py`
- `src/pipeline/pipeline_runner.py`
- `src/queue/single_node_runner.py`
- `src/controller/job_service.py`

## Tests

- `tests/utils/test_inmemory_log_handler.py`
- `tests/utils/test_logger_integration.py`

## Deferred Follow-On

- `PR-OBS-249B-Log-Trace-Panel-Severity-Coloring-and-Event-Filters`
- `PR-OBS-249C-Repeated-Event-Collapse-and-WebUI-Outage-Dedup`
- `PR-OBS-249D-Operator-vs-Trace-Log-Surface-Split`
