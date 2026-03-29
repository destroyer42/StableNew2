# PR-UX-278 - Dialog, Inspector, and Secondary Surface Consistency Sweep

Status: Completed 2026-03-26

## Summary

This PR extended the GUI consistency sweep into dialogs, inspectors, and other
secondary surfaces that were still lagging behind the main tabs in dark-mode,
scrollability, and minimum-size behavior.

## Delivered

- added horizontal scrolling and no-wrap inspection for the artifact metadata
  inspector
- made the learning review dialog scrollable for long record lists and applied
  consistent dark themed canvas styling
- added explicit stage-tree and config-snapshot scrollbars in the job
  explanation panel
- normalized review-side secondary popups so compare/import helper windows use
  the shared dark theme and explicit minimum sizes
- added focused GUI regressions for the updated dialog and secondary-surface
  seams

## Key Files

- `src/gui/artifact_metadata_inspector_dialog.py`
- `src/gui/learning_review_dialog_v2.py`
- `src/gui/panels_v2/job_explanation_panel_v2.py`
- `src/gui/views/review_tab_frame_v2.py`
- `tests/gui_v2/test_artifact_metadata_inspector_dialog.py`
- `tests/gui_v2/test_dialog_theme_v2.py`
- `tests/gui_v2/test_job_explanation_panel_v2.py`
- `tests/gui_v2/test_reprocess_panel_v2.py`

## Validation

Focused validation run:

`c:/Users/rob/projects/StableNew/.venv/Scripts/python.exe -m pytest tests/gui_v2/test_artifact_metadata_inspector_dialog.py tests/gui_v2/test_dialog_theme_v2.py tests/gui_v2/test_job_explanation_panel_v2.py tests/gui_v2/test_reprocess_panel_v2.py -q`

Result:

- `18 passed, 2 skipped`
