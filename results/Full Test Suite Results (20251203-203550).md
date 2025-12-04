# Full Test Suite Results — 2025-12-04 02:35:50Z

**Summary:** `pytest` exited with code 124 after the first batch of failures; see below for failing tests.

## Failed Tests (selected)
- `tests/api/test_webui_process_manager.py` — failed during the most recent run; inspect the pytest log for details.
- `tests/controller/test_adetailer_stage_integration_v2.py` — failed during the most recent run; inspect the pytest log for details.
- `tests/controller/test_app_controller_config.py` — failed during the most recent run; inspect the pytest log for details.
- `tests/controller/test_app_controller_packs.py` — failed during the most recent run; inspect the pytest log for details.
- `tests/controller/test_app_controller_pipeline_bridge.py` — failed during the most recent run; inspect the pytest log for details.
- `tests/controller/test_app_controller_pipeline_flow_pr0.py` — failed during the most recent run; inspect the pytest log for details.
- `tests/controller/test_app_controller_pipeline_integration.py` — failed during the most recent run; inspect the pytest log for details.
- `tests/controller/test_app_controller_run_mode_defaults.py` — failed during the most recent run; inspect the pytest log for details.
- `tests/controller/test_app_controller_run_now_bridge.py` — failed during the most recent run; inspect the pytest log for details.
- `tests/controller/test_app_to_pipeline_run_bridge_v2.py` — failed during the most recent run; inspect the pytest log for details.
- `tests/controller/test_job_history_service.py` — failed during the most recent run; inspect the pytest log for details.
- `tests/controller/test_resource_refresh_v2.py` — failed during the most recent run; inspect the pytest log for details.
- `tests/gui_v2/test_entrypoint_uses_v2_gui.py` — failed during the most recent run; inspect the pytest log for details.
- `tests/gui_v2/test_gui_v2_layout_skeleton.py` — failed during the most recent run; inspect the pytest log for details.
- `tests/gui_v2/test_pipeline_dropdown_refresh_v2.py` — failed during the most recent run; inspect the pytest log for details.
- `tests/gui_v2/test_pipeline_queue_preview_v2.py` — failed during the most recent run; inspect the pytest log for details.
- `tests/gui_v2/test_stage_cards_layout_v2.py` — failed during the most recent run; inspect the pytest log for details.
- `tests/gui_v2/test_status_bar_v2.py` — failed during the most recent run; inspect the pytest log for details.
- `tests/journey/test_phase1_pipeline_journey_v2.py` — failed during the most recent run; inspect the pytest log for details.
- `tests/journeys/test_jt03_txt2img_pipeline_run.py` — failed during the most recent run; inspect the pytest log for details.
- `tests/journeys/test_jt04_img2img_adetailer_run.py` — failed during the most recent run; inspect the pytest log for details.
- `tests/journeys/test_jt05_upscale_stage_run.py` — failed during the most recent run; inspect the pytest log for details.

## Command Used

```
python -m pytest
```

## Notes

- Many GUI/controller/journey tests failed early so the run aborted with exit code 124.
- See the pytest log for detailed failure tracebacks before rerunning.