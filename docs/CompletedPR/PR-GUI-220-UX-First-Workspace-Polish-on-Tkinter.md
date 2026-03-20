# PR-GUI-220 - UX-First Workspace Polish on Tkinter

Status: Completed 2026-03-20

## Summary

This PR tightened the day-to-day workspace flow without changing toolkits or
runtime architecture. The Tk workspace now behaves more like one coherent
product across History, Video Workflow, and Movie Clips instead of several
adjacent surfaces with thin handoff paths.

The underlying execution model remains unchanged:

`GUI Intent -> AppController/VideoWorkflowController -> NJR -> JobService Queue -> PipelineRunner`

## Delivered

- added `src/gui/view_contracts/video_workspace_contract.py` for shared
  workspace summaries, empty states, and workflow capability labels
- added `src/gui/controllers/video_workspace_handoff.py` for reusable
  cross-surface routing into `Video Workflow` and `Movie Clips`
- updated `src/gui/views/video_workflow_tab_frame_v2.py` with source-summary
  labels, workflow capability detail, bundle-aware handoff state, and clearer
  latest-output behavior
- updated `src/gui/views/movie_clips_tab_frame_v2.py` with source summaries,
  latest-video intake, and clearer build-result/status messaging
- updated `src/gui/job_history_panel_v2.py` with an explicit `Movie Clips`
  action, better empty-state messaging, and tighter action gating based on
  actual usable handoff sources
- added minimal glue in `src/controller/app_controller.py` and
  `src/gui/main_window_v2.py` so history and top-level tabs can route sources
  cleanly without changing queue/runtime semantics

## Key Files

- `src/gui/view_contracts/video_workspace_contract.py`
- `src/gui/controllers/video_workspace_handoff.py`
- `src/gui/views/video_workflow_tab_frame_v2.py`
- `src/gui/views/movie_clips_tab_frame_v2.py`
- `src/gui/job_history_panel_v2.py`
- `src/gui/main_window_v2.py`
- `src/controller/app_controller.py`

## Tests

Focused verification passed:

- `pytest tests/gui_v2/test_video_workspace_handoff.py tests/gui_v2/test_job_history_panel_v2.py tests/gui_v2/test_video_workflow_tab_frame_v2.py tests/gui_v2/test_movie_clips_tab_v2.py tests/gui_v2/test_main_window_persistence_regressions.py -q`
- `pytest tests/controller/test_app_controller_svd.py tests/gui_v2/test_video_workspace_handoff.py tests/gui_v2/test_job_history_panel_v2.py tests/gui_v2/test_video_workflow_tab_frame_v2.py tests/gui_v2/test_movie_clips_tab_v2.py tests/gui_v2/test_main_window_persistence_regressions.py -q`
- `pytest --collect-only -q -rs` -> `2534 collected / 0 skipped`
- `python -m compileall src/gui/controllers/video_workspace_handoff.py src/gui/view_contracts/video_workspace_contract.py src/gui/views/video_workflow_tab_frame_v2.py src/gui/views/movie_clips_tab_frame_v2.py src/gui/job_history_panel_v2.py src/gui/main_window_v2.py src/controller/app_controller.py tests/gui_v2/test_video_workspace_handoff.py tests/gui_v2/test_job_history_panel_v2.py tests/gui_v2/test_video_workflow_tab_frame_v2.py tests/gui_v2/test_movie_clips_tab_v2.py`

## Deferred Debt

The following remains intentionally deferred to `PR-CTRL-221`:

- replacing more direct GUI use of the `run_config` dict projection with a
  dedicated GUI config adapter
- additional controller shrink so workspace polish does not keep growing
  `AppController`
- richer continuity/story-plan exposure on top of the improved video workspace
