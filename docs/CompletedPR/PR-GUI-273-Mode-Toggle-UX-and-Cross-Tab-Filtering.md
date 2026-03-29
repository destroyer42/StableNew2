# PR-GUI-273 - Mode Toggle UX and Cross-Tab Filtering

Status: Completed 2026-03-27

## Summary

This PR exposed the global content-visibility toggle in the v2 shell and wired
the mounted content-heavy surfaces to refresh live when the mode changes.

## Delivered

- added a live `Visibility: NSFW/SFW` shell control in
  `src/gui/main_window_v2.py`
- wired prompt, preview, review, learning, photo-optimize, movie-clips, and
  video-workflow tab frames to refresh immediately on visibility-mode changes
- wired queue, running-job, and history panels for live mode awareness and
  lightweight SFW notices
- routed prompt-pack and learning-review notices through the same resolver-aware
  UX path
- added integration coverage for shell toggle behavior, prompt-pack filtering,
  preview redaction, review redaction, and photo-optimize redaction

## Key Files

- `src/gui/main_window_v2.py`
- `src/gui/views/prompt_tab_frame_v2.py`
- `src/gui/prompt_pack_panel_v2.py`
- `src/gui/widgets/lora_picker_panel.py`
- `src/gui/preview_panel_v2.py`
- `src/gui/panels_v2/queue_panel_v2.py`
- `src/gui/panels_v2/running_job_panel_v2.py`
- `src/gui/panels_v2/history_panel_v2.py`
- `src/gui/views/review_tab_frame_v2.py`
- `src/gui/views/learning_tab_frame_v2.py`
- `src/gui/views/learning_review_panel_v2.py`
- `src/gui/views/photo_optimize_tab_frame_v2.py`
- `src/gui/views/movie_clips_tab_frame_v2.py`
- `src/gui/views/video_workflow_tab_frame_v2.py`
- `tests/gui_v2/test_content_visibility_toggle_integration.py`

## Tests

Focused verification passed:

- `pytest -q tests/gui_v2/test_content_visibility_toggle_integration.py`
- `pytest -q tests/gui_v2/test_main_window_smoke_v2.py tests/gui_v2/test_preview_panel_v2_normalized_jobs.py tests/gui_v2/test_lora_picker_panel_v2.py tests/gui_v2/test_review_tab_prompt_modes.py tests/gui_v2/test_photo_optimize_tab_v2.py tests/gui_v2/test_running_job_panel_v2.py tests/gui_v2/test_movie_clips_tab_v2.py tests/gui_v2/test_video_workflow_tab_frame_v2.py`
- `pytest -q tests/gui_v2/test_action_explainer_panels_v2.py tests/gui_v2/test_queue_run_controls_restructure_v2.py tests/gui_v2/test_job_history_panel_v2.py tests/gui_v2/test_job_history_panel_display.py`
- `python -m compileall src/gui/main_window_v2.py src/gui/views/prompt_tab_frame_v2.py src/gui/prompt_pack_panel_v2.py src/gui/widgets/lora_picker_panel.py src/gui/preview_panel_v2.py src/gui/panels_v2/queue_panel_v2.py src/gui/panels_v2/running_job_panel_v2.py src/gui/panels_v2/history_panel_v2.py src/gui/views/review_tab_frame_v2.py src/gui/views/learning_tab_frame_v2.py src/gui/views/learning_review_panel_v2.py src/gui/views/photo_optimize_tab_frame_v2.py src/gui/views/movie_clips_tab_frame_v2.py src/gui/views/video_workflow_tab_frame_v2.py tests/gui_v2/test_content_visibility_toggle_integration.py`

## Documentation Updates

- `docs/StableNew Roadmap v2.6.md`
- `docs/DOCS_INDEX_v2.6.md`
- `docs/PR_Backlog/PR-GUI-273-Mode-Toggle-UX-and-Cross-Tab-Filtering.md`

## Notes

This PR kept resolver policy centralized. The GUI work was limited to shell
exposure, surface subscriptions, live refreshes, and lightweight operator
messaging.
