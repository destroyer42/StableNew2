# PR-GUI-286 - Incremental Projection Reconciliation and Visibility Gating

Status: Completed 2026-03-29

## Delivered

- pipeline-shell hot surfaces now defer queue/history/preview/running work while hidden
- non-pipeline hot surfaces now defer visibility-driven refresh work until mapped
- hidden photo-optimize asset/resource refreshes and hidden SVD recent-history refreshes no longer spend Tk time while unmapped
- Debug Hub hot refreshes now follow the same visibility-gated discipline

## Validation

- `tests/gui_v2/test_prompt_tab_layout_v2.py`
- `tests/gui_v2/test_svd_tab_frame_v2.py`
- `tests/gui_v2/test_photo_optimize_tab_v2.py`
- `tests/gui_v2/test_learning_tab_state_persistence.py`
- `tests/gui_v2/test_debug_hub_panel_v2.py`
- `tests/gui_v2/test_review_tab_prompt_modes.py`
- `tests/gui_v2/test_movie_clips_tab_v2.py`
- `tests/gui_v2/test_video_workflow_tab_frame_v2.py`
