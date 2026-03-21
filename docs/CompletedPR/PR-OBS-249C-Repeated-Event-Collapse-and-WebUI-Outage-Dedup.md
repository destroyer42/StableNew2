# PR-OBS-249C - Repeated Event Collapse and WebUI Outage Dedup

Status: Completed 2026-03-21

## Summary

This PR reduced log spam during repeated outages and retries by collapsing
identical events inside the GUI log handler and preserving repeat metadata.

## Delivered

- repeat-aware `InMemoryLogHandler` entries with `repeat_count`,
  `first_created`, and `last_created`
- GUI rendering of repeat summaries in `src/gui/log_trace_panel_v2.py`
- alignment with the earlier WebUI resource-endpoint cooldown work in
  `src/api/client.py`

## Tests

- `tests/utils/test_inmemory_log_handler.py`
- `tests/test_api_client.py`
- `tests/gui_v2/test_log_trace_panel_v2.py`
- included in the focused logging verification run: `63 passed`
