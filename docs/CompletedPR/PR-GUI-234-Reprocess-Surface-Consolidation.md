# PR-GUI-234 - Reprocess Surface Consolidation

Status: Completed 2026-03-20

## Summary

This PR removed the duplicate advanced reprocess surface from the Pipeline
sidebar and made Review the single obvious home for advanced reprocess work.

## Delivered

- collapsed the sidebar reprocess card into a lightweight Review launcher
- removed duplicated sidebar image-selection, filtering, stage-selection, and
  submit controls
- marked Review as the canonical advanced reprocess workspace with explicit UI
  guidance
- kept the existing queue-backed Review reprocess path unchanged

## Key Files

- `src/gui/panels_v2/reprocess_panel_v2.py`
- `src/gui/views/review_tab_frame_v2.py`
- `tests/gui_v2/test_reprocess_panel_v2.py`
- `tests/controller/test_app_controller_reprocess_review_tab.py`

## Tests

Focused verification passed:

- `pytest tests/gui_v2/test_reprocess_panel_v2.py tests/controller/test_app_controller_reprocess_review_tab.py -q`
- `python -m compileall src/gui/panels_v2/reprocess_panel_v2.py src/gui/views/review_tab_frame_v2.py tests/gui_v2/test_reprocess_panel_v2.py`

## Documentation Updates

Bookkeeping closure recorded in:

- `docs/StableNew Roadmap v2.6.md`
- `docs/PR_Backlog/PR-GUI-234-Reprocess-Surface-Consolidation.md`

## Deferred Debt

Intentionally deferred:

- Pipeline tab base-generation and recipe-summary cleanup
  Future owner: `PR-GUI-235`
