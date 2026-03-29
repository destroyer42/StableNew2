# PR-UX-267 - Stage-Card Settings Help and Config Intent Descriptions

Status: Completed 2026-03-25
Priority: HIGH
Effort: MEDIUM
Phase: Immediate UX Help Sweep

## Summary

Added operator-facing tooltip coverage for the most important stage-card and
video settings so users can inspect what each control does, when to raise or
lower it, and the main quality, speed, fidelity, or risk tradeoffs without
leaving the GUI.

## Delivered

- added a centralized `stage_setting_help_v2` help-text map for shared pipeline
  and video setting guidance
- added reusable setting-tooltip registration support in the active V2 stage-card
  base class so help text stays test-visible and consistent across cards
- added setting help coverage for shared Base Generation controls including model,
  VAE, sampler, scheduler, steps, CFG, resolution, seed, subseed, and subseed
  strength
- added setting help coverage across the main stage cards:
  - Txt2Img
  - Img2Img
  - ADetailer
  - Upscale
- extended the same help pattern into video-related setting forms on:
  - `SVD Img2Vid`
  - `Video Workflow`
  - `Movie Clips`
- added focused GUI tests for representative setting-help tooltips and stabilized
  the adjacent ADetailer visibility test with an explicit idle-layout pump

## Key Files

- `src/gui/help_text/stage_setting_help_v2.py`
- `src/gui/stage_cards_v2/base_stage_card_v2.py`
- `src/gui/base_generation_panel_v2.py`
- `src/gui/stage_cards_v2/advanced_txt2img_stage_card_v2.py`
- `src/gui/stage_cards_v2/advanced_img2img_stage_card_v2.py`
- `src/gui/stage_cards_v2/advanced_upscale_stage_card_v2.py`
- `src/gui/stage_cards_v2/adetailer_stage_card_v2.py`
- `src/gui/views/svd_tab_frame_v2.py`
- `src/gui/views/video_workflow_tab_frame_v2.py`
- `src/gui/views/movie_clips_tab_frame_v2.py`
- `tests/gui_v2/test_stage_setting_help_v2.py`

## Validation

- focused GUI slice:
  - `pytest tests/gui_v2/test_stage_setting_help_v2.py tests/gui_v2/test_pipeline_base_generation_ownership_v2.py tests/gui_v2/test_pipeline_adetailer_toggle_v2.py tests/gui_v2/test_action_explainer_panels_v2.py tests/gui_v2/test_movie_clips_tab_v2.py tests/gui_v2/test_video_workflow_tab_frame_v2.py tests/gui_v2/test_svd_tab_frame_v2.py -q`
  - `70 passed, 1 skipped in 5.96s`

## Notes

- the remaining editor diagnostics in some touched files are unrelated pre-existing
  type-check noise; the PR-UX-267 implementation compiles and the focused GUI
  validation slice passes