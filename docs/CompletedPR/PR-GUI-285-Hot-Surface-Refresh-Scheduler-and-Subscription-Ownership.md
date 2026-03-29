# PR-GUI-285 - Hot Surface Refresh Scheduler and Subscription Ownership

Status: Completed 2026-03-28

## Delivered

- `PipelineTabFrameV2` now owns hot queue/history/preview shell refresh scheduling
- queue/history/preview panels can operate standalone, but pipeline-shell instances
  disable child hot subscriptions and reconcile through one owner
- diagnostics now include hot-surface scheduler metrics

## Validation

- `tests/gui_v2/test_pipeline_tab_callback_metrics_v2.py`
- `tests/controller/test_app_controller_diagnostics.py`
- `tests/gui_v2/test_job_history_panel_v2.py`
- `tests/gui_v2/test_job_history_panel_display.py`
- `tests/gui_v2/test_queue_run_controls_restructure_v2.py`
