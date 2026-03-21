# PR-GUI-235A - PresetNaming Cleanup for Saved Recipes

Status: Implemented 2026-03-21

## Purpose

Finish the active Pipeline v2 naming cleanup after `PR-GUI-235` so the live
sidebar and controller surface use `Saved Recipe` terminology instead of
`Preset` terminology.

## Scope

- rename active sidebar recipe state and callbacks to `saved_recipe_*`
- rename active pipeline controller callbacks to `saved_recipe` terminology
- update focused GUI/controller tests to the new names
- keep `ConfigManager` storage and on-disk `presets/` layout unchanged

## Delivered

- `src/gui/sidebar_panel_v2.py`
- `src/controller/app_controller.py`
- `tests/gui_v2/test_sidebar_presets_v2.py`
- `tests/gui_v2/test_pipeline_presets_ui_v2.py`
- `tests/controller/test_presets_integration_v2.py`

## Explicit Non-Goals

- no storage-contract rename in `ConfigManager`
- no migration of legacy `LeftZone` compatibility harness names
- no learning-driven recommendation behavior in this PR

## Verification

- covered by the focused `PR-GUI-235` verification suite plus adjacent
  pipeline/main-window regressions
