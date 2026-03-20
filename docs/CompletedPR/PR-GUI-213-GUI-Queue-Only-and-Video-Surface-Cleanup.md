# PR-GUI-213 - GUI Queue-Only and Video Surface Cleanup

Status: Completed 2026-03-19

## Summary

This PR removes the last live `PipelineConfigPanel` runtime coupling from the
active GUI/controller path and adds the first dedicated workflow-driven video
surface without introducing a second submission model.

Fresh GUI submission remains:

`GUI Intent -> AppController/VideoWorkflowController -> NJR -> JobService Queue -> PipelineRunner`

## Delivered

- removed active `pipeline_config_panel_v2` lookups from
  `AppController` and `MainWindowV2`
- kept the archived panel module available only as a compatibility/test shim,
  not as a live runtime dependency
- added a dedicated `Video Workflow` tab for workflow-driven video submission
- persisted `Video Workflow` tab state through the canonical UI state store
- added `VideoWorkflowController` to keep workflow-video submission queue/NJR-only
- added history handoff from image outputs into:
  - `Animate with SVD`
  - `Video Workflow`
- disabled both history handoff actions for entries whose primary artifact is a
  video artifact

## Key Files

- `src/controller/app_controller.py`
- `src/controller/video_workflow_controller.py`
- `src/gui/main_window_v2.py`
- `src/gui/job_history_panel_v2.py`
- `src/gui/views/video_workflow_tab_frame_v2.py`

## Tests

Focused verification passed:

- `pytest tests/gui_v2/test_job_history_panel_v2.py tests/controller/test_app_controller_svd.py tests/gui_v2/test_main_window_persistence_regressions.py tests/gui_v2/test_pipeline_left_column_config_v2.py tests/controller/test_pipeline_randomizer_config_v2.py tests/controller/test_presets_integration_v2.py tests/gui_v2/test_video_workflow_tab_frame_v2.py tests/controller/test_video_workflow_controller.py -q`
- `pytest tests/system/test_architecture_enforcement_v2.py tests/gui_v2/test_job_history_panel_display.py tests/gui_v2/test_pipeline_layout_scroll_v2.py tests/controller/test_app_controller_run_bridge_v2.py tests/controller/test_app_controller_pipeline_integration.py -q`
- `pytest --collect-only -q -rs` -> `2384 collected / 0 skipped`
- `python -m compileall src/controller/video_workflow_controller.py src/gui/views/video_workflow_tab_frame_v2.py src/gui/main_window_v2.py src/gui/job_history_panel_v2.py src/controller/app_controller.py tests/gui_v2/test_video_workflow_tab_frame_v2.py tests/controller/test_video_workflow_controller.py`

## Deferred Debt

The following remains intentionally deferred to `PR-POLISH-214`:

- final cleanup of residual `PipelineConfigPanel` naming/history in compat and archive-adjacent surfaces
- further controller monolith reduction beyond this GUI-facing cut
- replacement of `AppStateV2.run_config` as a dict façade with a richer GUI-facing
  adapter over the canonical config layers
