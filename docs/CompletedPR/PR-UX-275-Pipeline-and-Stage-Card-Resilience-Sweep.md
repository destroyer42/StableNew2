# PR-UX-275 - Pipeline and Stage-Card Resilience Sweep

Status: Completed 2026-03-26

## Summary

This PR applies the shared layout baseline from `PR-UX-274` to the active
pipeline host and the remaining dense stage-card surfaces that still relied on
local resize behavior.

It fixes the mismatch between pipeline column minimums and the window minimum,
normalizes stacked stage-card row behavior, and moves ADetailer plus the txt2img
refiner and hires subforms onto the shared label/control sizing discipline.

## Delivered

- updated the Pipeline tab to use realistic column minimums instead of treating
  the default working width as the minimum width
- added explicit minimum-width discipline to the left, center, and right
  scrollable pipeline columns
- standardized stage-card stacking so rows keep their natural height instead of
  competing for equal expansion
- moved ADetailer overall, tab, and prompt grids onto shared form-column rules
- made ADetailer numeric controls expand with the shared control-width baseline
- moved txt2img refiner and hires option subforms onto shared single-pair
  label/control rules
- added focused GUI regressions for pipeline column minimums and the new stage
  card resilience seams

## Key Files

- `src/gui/views/pipeline_tab_frame_v2.py`
- `src/gui/views/stage_cards_panel_v2.py`
- `src/gui/stage_cards_v2/adetailer_stage_card_v2.py`
- `src/gui/stage_cards_v2/advanced_txt2img_stage_card_v2.py`
- `tests/gui_v2/test_stage_card_layout_resilience_v2.py`

## Validation

Focused validation run:

`c:/Users/rob/projects/StableNew/.venv/Scripts/python.exe -m pytest tests/gui_v2/test_pipeline_view_contracts.py tests/gui_v2/test_zone_map_card_order_v2.py tests/gui_v2/test_pipeline_tab_layout_v2.py tests/gui_v2/test_window_layout_normalization_v2.py tests/gui_v2/test_stage_card_layout_resilience_v2.py -q`

Result:

- `9 passed, 2 skipped in 1.94s`

## Notes

- pre-existing Tk typing diagnostics remain in older GUI files and are outside
  this PR scope
- the next canonical UX PR is
  `PR-UX-276-Prompt-and-LoRA-Row-Usability-Sweep`