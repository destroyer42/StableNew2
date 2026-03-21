# PR-GUI-235 - Core Config to Base Generation and Recipe Summary UX

Status: Completed 2026-03-21

## Summary

This PR removed the live `Core Config` concept from the active Pipeline v2
path and replaced it with a real `Base Generation` ownership boundary. It also
made saved pipeline configs readable in the sidebar as `Saved Recipes` instead
of an opaque preset dropdown.

## Delivered

- replaced the active sidebar panel with
  `src/gui/base_generation_panel_v2.py`
- deleted the live `src/gui/core_config_panel_v2.py` module
- added `src/gui/recipe_summary_v2.py` for readable recipe summaries
- updated `src/gui/sidebar_panel_v2.py` so the active sidebar shows
  `Saved Recipes` and `Base Generation`
- updated `src/gui/views/pipeline_tab_frame_v2.py` so shared base fields now
  come from `Base Generation`
- updated `src/gui/views/stage_cards_panel_v2.py` so stage-card overrides no
  longer export shared txt2img-owned base fields
- updated `src/gui/stage_cards_v2/advanced_txt2img_stage_card_v2.py` so the
  txt2img card only owns stage-local fields when shared base generation is
  active
- updated `src/controller/app_controller.py`,
  `src/gui/dropdown_loader_v2.py`, `src/gui/main_window_v2.py`, and
  `src/main.py` to follow the new base-generation ownership path

## Key Files

- `src/gui/base_generation_panel_v2.py`
- `src/gui/recipe_summary_v2.py`
- `src/gui/sidebar_panel_v2.py`
- `src/gui/views/pipeline_tab_frame_v2.py`
- `src/gui/views/stage_cards_panel_v2.py`
- `src/gui/stage_cards_v2/advanced_txt2img_stage_card_v2.py`
- `src/controller/app_controller.py`
- `src/gui/dropdown_loader_v2.py`
- `src/gui/main_window_v2.py`
- `src/main.py`

## Tests

Focused verification passed:

- `pytest tests/gui_v2/test_core_config_webui_resources_v2.py tests/gui_v2/test_core_config_controller.py tests/gui_v2/test_gui_v2_layout_skeleton.py tests/gui_v2/test_sidebar_presets_v2.py tests/gui_v2/test_pipeline_presets_ui_v2.py tests/gui_v2/test_pipeline_base_generation_ownership_v2.py tests/gui_v2/test_recipe_summary_v2.py tests/controller/test_presets_integration_v2.py tests/controller/test_app_controller_config.py -q`
  - result: `15 passed, 1 skipped`
- `pytest tests/gui_v2/test_pipeline_layout_scroll_v2.py tests/controller/test_app_controller_pipeline_integration.py tests/gui_v2/test_main_window_persistence_regressions.py -q`
  - result: `18 passed`
- `python -m compileall src/gui/base_generation_panel_v2.py src/gui/recipe_summary_v2.py src/gui/sidebar_panel_v2.py src/gui/views/pipeline_tab_frame_v2.py src/gui/views/stage_cards_panel_v2.py src/gui/stage_cards_v2/advanced_txt2img_stage_card_v2.py src/controller/app_controller.py`

## Deferred Debt

Intentionally deferred to future work:

- storage-contract rename away from `ConfigManager` `preset*` APIs
- learning-based recommendations on top of `Saved Recipes`
- cleanup of legacy non-active `LeftZone` preset naming
