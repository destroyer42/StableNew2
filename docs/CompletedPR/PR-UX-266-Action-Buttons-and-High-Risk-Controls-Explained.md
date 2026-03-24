# PR-UX-266 - Action Buttons and High-Risk Controls Explained

Status: Completed 2026-03-24
Priority: HIGH
Effort: MEDIUM
Phase: Immediate UX Help Sweep

## Summary

Added shared inline action-explainer panels and targeted tooltip coverage so the
most important queue, review, learning, and video controls explain what they do
before the operator clicks them.

## Delivered

- added a reusable `ActionExplainerPanel` widget for always-visible action and
  workflow guidance
- added queue action semantics for:
  - auto-run queue
  - send job
  - pause queue
  - reorder/remove/clear queue controls
- clarified review actions for:
  - import selected to learning
  - import recent job
  - reprocess selected
  - reprocess all
- clarified staged curation bulk-queue versus single-candidate Review paths in
  Learning
- added workflow-choice and settings-intent guidance across:
  - `SVD Img2Vid`
  - `Video Workflow`
  - `Movie Clips`
- exposed tooltip handles on widgets so the new operator guidance can be tested
  directly in focused GUI coverage

## Key Files

- `src/gui/widgets/action_explainer_panel_v2.py`
- `src/gui/tooltip.py`
- `src/gui/panels_v2/queue_panel_v2.py`
- `src/gui/views/review_tab_frame_v2.py`
- `src/gui/views/learning_tab_frame_v2.py`
- `src/gui/views/svd_tab_frame_v2.py`
- `src/gui/views/video_workflow_tab_frame_v2.py`
- `src/gui/views/movie_clips_tab_frame_v2.py`
- `tests/gui_v2/test_action_explainer_panels_v2.py`

## Validation

- focused GUI slice:
  - `pytest tests/gui_v2/test_action_explainer_panels_v2.py tests/gui_v2/test_tab_overview_panels_v2.py tests/gui_v2/test_queue_run_controls_restructure_v2.py tests/gui_v2/test_movie_clips_tab_v2.py tests/gui_v2/test_video_workflow_tab_frame_v2.py tests/gui_v2/test_svd_tab_frame_v2.py tests/gui_v2/test_review_tab_prompt_modes.py tests/gui_v2/test_learning_tab_state_persistence.py -q`
  - `99 passed, 1 skipped in 6.13s`

## Notes

- this PR intentionally stayed centered on action semantics and workflow choice
  guidance rather than attempting the broader all-settings tooltip sweep queued
  under later UX help PRs