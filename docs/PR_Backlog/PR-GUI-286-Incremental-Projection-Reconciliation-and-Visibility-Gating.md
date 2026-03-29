# PR-GUI-286 - Incremental Projection Reconciliation and Visibility Gating

Status: Completed 2026-03-29

## Purpose

Finish the hot-surface projection side so invisible queue/history/preview work
does not keep consuming Tk time while jobs are running.

## Delivered

- pipeline hot-surface scheduler now defers queue/history/preview/running-panel
  work when the destination surface is unmapped
- deferred hot surfaces are retained and flushed when the pipeline tab maps again
- preview thumbnail async apply now skips hidden-widget image mutation and
  relies on cached lookup results for later visible refreshes
- prompt, review, learning, photo-optimize, movie clips, video workflow, SVD,
  and Debug Hub hot surfaces now defer visibility-driven refresh work until mapped
- hidden asset/resource updates in photo-optimize and hidden recent-history updates
  in SVD no longer burn Tk time while their surfaces are unmapped
- deterministic hidden-surface coverage now exists for the non-pipeline sweep

## Validation

- `tests/gui_v2/test_prompt_tab_layout_v2.py`
- `tests/gui_v2/test_svd_tab_frame_v2.py`
- `tests/gui_v2/test_photo_optimize_tab_v2.py`
- `tests/gui_v2/test_learning_tab_state_persistence.py`
- `tests/gui_v2/test_debug_hub_panel_v2.py`
- `tests/gui_v2/test_review_tab_prompt_modes.py`
- `tests/gui_v2/test_movie_clips_tab_v2.py`
- `tests/gui_v2/test_video_workflow_tab_frame_v2.py`

## Key Files

- `src/gui/views/pipeline_tab_frame_v2.py`
- `src/gui/preview_panel_v2.py`
- `src/gui/views/prompt_tab_frame_v2.py`
- `src/gui/views/review_tab_frame_v2.py`
- `src/gui/views/learning_tab_frame_v2.py`
- `src/gui/views/photo_optimize_tab_frame_v2.py`
- `src/gui/views/movie_clips_tab_frame_v2.py`
- `src/gui/views/video_workflow_tab_frame_v2.py`
- `src/gui/views/svd_tab_frame_v2.py`
- `src/gui/panels_v2/debug_hub_panel_v2.py`
