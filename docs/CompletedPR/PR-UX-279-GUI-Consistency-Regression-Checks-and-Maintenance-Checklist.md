# PR-UX-279 - GUI Consistency Regression Checks and Maintenance Checklist

Status: Completed 2026-03-26

## Summary

This PR converts the dark-mode and layout sweep into durable maintenance
standards by adding a living checklist doc and a compact cross-cutting GUI
regression anchor.

## Delivered

- added an active GUI consistency maintenance checklist covering:
  - dark-mode compliance
  - minimum widths and geometry
  - resize behavior
  - long-content handling
  - secondary-surface parity
  - test and docs housekeeping expectations
- added a compact GUI regression file that re-checks representative secondary
  surfaces and workspace layout contracts
- updated the active docs index so the checklist is part of the v2.6 active
  subsystem references
- updated the GUI dark-mode/layout sweep backlog doc so `PR-UX-278` and
  `PR-UX-279` completion state is explicit

## Key Files

- `docs/Subsystems/GUI/GUI_CONSISTENCY_MAINTENANCE_CHECKLIST_v2.6.md`
- `docs/DOCS_INDEX_v2.6.md`
- `docs/CompletedPlans/GUI_DARK_MODE_AND_LAYOUT_CONSISTENCY_SWEEP_v2.6.md`
- `tests/gui_v2/test_gui_consistency_maintenance_v2.py`

## Validation

Focused validation run:

`c:/Users/rob/projects/StableNew/.venv/Scripts/python.exe -m pytest tests/gui_v2/test_gui_consistency_maintenance_v2.py tests/gui_v2/test_theming_dark_mode_v2.py tests/gui_v2/test_window_layout_normalization_v2.py tests/gui_v2/test_workspace_layout_resilience_v2.py -q`

Result:

- `19 passed, 1 skipped`
