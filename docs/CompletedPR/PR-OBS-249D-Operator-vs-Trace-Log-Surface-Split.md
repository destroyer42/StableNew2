# PR-OBS-249D - Operator vs Trace Log Surface Split

Status: Completed 2026-03-21

## Summary

This PR separated the audiences for the two GUI log surfaces: the bottom panel
is now the operator feed and the Debug Hub is the detailed trace surface.

## Delivered

- audience-aware `LogTracePanelV2`
- bottom panel wired as `audience="operator"` in `src/gui/main_window_v2.py`
- Debug Hub wired as `audience="trace"` in
  `src/gui/panels_v2/debug_hub_panel_v2.py`
- operator-mode filtering that keeps lifecycle info, warnings, and errors while
  hiding detailed payload/config noise

## Tests

- `tests/gui_v2/test_log_display_v2.py`
- `tests/gui_v2/test_log_trace_panel_v2.py`
- included in the focused logging verification run: `63 passed`
