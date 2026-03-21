# PR-GUI-235A - PresetNaming Cleanup

Status: Completed 2026-03-21

## Summary

This follow-on cleanup aligned the active Pipeline v2 sidebar/controller naming
with the new `Saved Recipe` language introduced in `PR-GUI-235`. The goal was
to stop the live GUI path from speaking in `preset` terms while keeping the
existing `ConfigManager` storage boundary stable.

## Delivered

- renamed active sidebar recipe variables and handlers in
  `src/gui/sidebar_panel_v2.py` to `saved_recipe_*`
- renamed active pipeline controller callbacks in
  `src/controller/app_controller.py` to `saved_recipe` terminology
- updated focused GUI/controller tests to the new active-path naming

## Key Files

- `src/gui/sidebar_panel_v2.py`
- `src/controller/app_controller.py`
- `tests/gui_v2/test_sidebar_presets_v2.py`
- `tests/gui_v2/test_pipeline_presets_ui_v2.py`
- `tests/controller/test_presets_integration_v2.py`

## Tests

Covered by the `PR-GUI-235` focused verification suite:

- `pytest tests/gui_v2/test_core_config_webui_resources_v2.py tests/gui_v2/test_core_config_controller.py tests/gui_v2/test_gui_v2_layout_skeleton.py tests/gui_v2/test_sidebar_presets_v2.py tests/gui_v2/test_pipeline_presets_ui_v2.py tests/gui_v2/test_pipeline_base_generation_ownership_v2.py tests/gui_v2/test_recipe_summary_v2.py tests/controller/test_presets_integration_v2.py tests/controller/test_app_controller_config.py -q`
  - result: `15 passed, 1 skipped`

## Deferred Debt

Still intentionally deferred:

- `ConfigManager` on-disk/storage terminology still uses `preset`
- legacy `LeftZone` compatibility harness names still use `preset`
- learning-backed recommendation ranking remains a future layer on top of
  `Saved Recipes`, not part of this rename PR
