# PR-OBS-249B - Log Trace Panel Severity Coloring and Event Filters

Status: Implemented 2026-03-21
Priority: HIGH
Effort: SMALL
Phase: Observability and Logging
Date: 2026-03-21

## Summary

Make the detailed GUI log surface materially more useful by adding severity
coloring, stage/event-aware filtering, and a clearer rendered line format.

## Delivered

- updated `src/gui/log_trace_panel_v2.py` with severity-colored text tags
- removed the redundant `DEBUG+` selector state and kept `ALL`, `INFO+`,
  `WARN+`, and `ERROR`
- added trace-surface filters for `subsystem`, `stage`, `event`, and `job_id`
- improved rendering with compact ASCII badges and structured payload summaries
- kept the crash-bundle hook and existing handler surface intact

## Key Files

- `src/gui/log_trace_panel_v2.py`
- `tests/gui_v2/test_log_trace_panel_v2.py`
- `tests/gui_v2/test_log_display_v2.py`

## Deferred Follow-On

- `PR-OBS-249C-Repeated-Event-Collapse-and-WebUI-Outage-Dedup`
- `PR-OBS-249D-Operator-vs-Trace-Log-Surface-Split`
