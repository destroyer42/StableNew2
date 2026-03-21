# PR-OBS-249D - Operator vs Trace Log Surface Split

Status: Implemented 2026-03-21
Priority: HIGH
Effort: SMALL
Phase: Observability and Logging
Date: 2026-03-21

## Summary

Make the bottom-of-window log an operator-focused surface and the Debug Hub the
detailed trace surface.

## Delivered

- `src/gui/main_window_v2.py` now instantiates the bottom panel as an operator
  log
- `src/gui/panels_v2/debug_hub_panel_v2.py` now instantiates the Debug Hub log
  as a trace surface
- `src/gui/log_trace_panel_v2.py` now supports audience-aware filtering and
  rendering
- operator mode suppresses debug/config/payload noise while preserving lifecycle
  info, warnings, and errors

## Key Files

- `src/gui/main_window_v2.py`
- `src/gui/panels_v2/debug_hub_panel_v2.py`
- `src/gui/log_trace_panel_v2.py`
- `tests/gui_v2/test_log_display_v2.py`
- `tests/gui_v2/test_log_trace_panel_v2.py`
