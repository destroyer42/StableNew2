# PR-GUI-285 - Hot Surface Refresh Scheduler and Subscription Ownership

Status: Completed 2026-03-28

## Purpose

Make `PipelineTabFrameV2` the single owner for hot queue/history/preview shell
refreshes so child panels stop independently repainting under runtime churn.

## Outcomes

- `PipelineTabFrameV2` owns hot-surface subscription scheduling
- queue/history/preview refreshes are coalesced into one pipeline-tab flush tick
- child panels can still subscribe in standalone usage, but the pipeline shell
  disables those subscriptions and owns the hot path
- diagnostics now expose scheduler-level flush metrics

## Key Files

- `src/gui/views/pipeline_tab_frame_v2.py`
- `src/gui/panels_v2/queue_panel_v2.py`
- `src/gui/job_history_panel_v2.py`
- `src/gui/preview_panel_v2.py`
- `tests/gui_v2/test_pipeline_tab_callback_metrics_v2.py`
- `tests/controller/test_app_controller_diagnostics.py`

## Validation

- hot-surface scheduler coalescing regression
- subscription-ownership regression
- diagnostics snapshot regression
