# PR-UX-273 - Shared Dark-Mode Tokens and Widget Theme Discipline

Status: Completed 2026-03-25

## Summary

This PR standardizes dark-mode behavior at the shared theme layer instead of
 fixing dialogs and helper widgets one by one.

It introduces reusable theme helpers for `Toplevel` windows and raw Tk text/list
 surfaces, then moves the biggest dialog and prompt-tooling outliers onto that
 shared path.

## Delivered

- expanded `src/gui/theme_v2.py` with:
  - generic dark-mode defaults for common ttk widgets
  - `apply_toplevel_theme(...)`
  - `style_text_widget(...)`
  - `style_listbox_widget(...)`
  - `style_canvas_widget(...)`
- removed the advanced prompt editor's local dark-style bootstrap in favor of
  the shared theme path
- moved the main dialog/inspector outliers onto the shared dark-mode helpers:
  - artifact metadata inspector
  - structured error modal
  - learning review dialog
  - multi-folder selector
  - job explanation panel
  - matrix helper dialogs
  - LoRA keyword dialog
  - config sweep raw text/list surfaces
- added focused GUI regressions for:
  - shared theme helpers
  - artifact metadata inspector dark-mode wiring
  - structured error modal dark-mode wiring
  - dark-mode behavior for representative utility dialogs

## Key Files

- `src/gui/theme_v2.py`
- `src/gui/advanced_prompt_editor.py`
- `src/gui/artifact_metadata_inspector_dialog.py`
- `src/gui/views/error_modal_v2.py`
- `src/gui/dialogs/multi_folder_selector.py`

## Validation

Focused validation run:

`c:/Users/rob/projects/StableNew/.venv/Scripts/python.exe -m pytest tests/gui_v2/test_theme_v2.py tests/gui_v2/test_artifact_metadata_inspector_dialog.py tests/gui_v2/test_error_modal_v2.py tests/gui_v2/test_dialog_theme_v2.py -q`

Result:

- `5 passed, 2 skipped in 2.31s`

## Notes

- pre-existing Tk typing noise remains in several older GUI files and is outside
  this PR scope
- the next canonical UX PR is
  `PR-UX-274-Shared-Layout-Minimums-and-Resize-Discipline`