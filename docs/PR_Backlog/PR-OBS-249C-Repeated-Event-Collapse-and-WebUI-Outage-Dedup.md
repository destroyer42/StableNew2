# PR-OBS-249C - Repeated Event Collapse and WebUI Outage Dedup

Status: Implemented 2026-03-21
Priority: HIGH
Effort: SMALL
Phase: Observability and Logging
Date: 2026-03-21

## Summary

Reduce operator and trace-panel spam during repeated outages or retries by
collapsing identical events in the GUI log handler and preserving repeat
counts.

## Delivered

- extended `InMemoryLogHandler` with repeat-aware accumulation
- rendered repeat summaries in the trace panel as
  `repeated Nx over Ts`
- preserved the first occurrence and stored first/last timestamps
- aligned this with the existing WebUI resource-endpoint cooldown path so
  `sd-models` and `sd-vae` failures do not flood the GUI view

## Key Files

- `src/utils/logger.py`
- `src/api/client.py`
- `src/gui/log_trace_panel_v2.py`
- `tests/utils/test_inmemory_log_handler.py`
- `tests/test_api_client.py`
- `tests/gui_v2/test_log_trace_panel_v2.py`

## Deferred Follow-On

- `PR-OBS-249D-Operator-vs-Trace-Log-Surface-Split`
