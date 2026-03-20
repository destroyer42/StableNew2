# PR-CTRL-221 - GUI Config Adapter and Final Controller Shrink

Status: Completed 2026-03-20

## Summary

This PR finished the remaining GUI-facing cleanup after the queue-only/NJR
unification work. The main goal was to stop treating `AppStateV2.run_config`
as the primary GUI config surface while reducing more top-level controller
responsibility without changing runtime behavior.

The resulting shape is:

`GUI Surface -> GuiConfigAdapterV26 / bounded controller service -> AppController / PipelineController -> NJR -> Queue -> Runner`

## Delivered

- added `src/gui/config_adapter_v26.py` as a stable GUI-facing facade over
  canonical `intent_config`, `execution_config`, and `backend_options`
- updated `src/gui/app_state_v2.py` so the adapter is exposed as the primary
  GUI config access surface, while `run_config` remains only as a derived
  compatibility projection
- added `src/controller/app_controller_services/gui_config_service.py` and
  moved GUI-facing config mutation/projection logic behind that service
- updated `src/controller/app_controller.py` so randomizer/config projection
  flows delegate through `GuiConfigService` instead of mutating the raw
  `run_config` dict directly
- updated `src/controller/app_controller_services/run_submission_service.py`
  so prompt-pack provenance can come from the GUI adapter rather than ad hoc
  draft inspection only
- added `src/controller/pipeline_controller_services/history_handoff_service.py`
  and moved replay hydration/handoff logic out of `PipelineController`

## Key Files

- `src/gui/config_adapter_v26.py`
- `src/gui/app_state_v2.py`
- `src/controller/app_controller_services/gui_config_service.py`
- `src/controller/app_controller.py`
- `src/controller/app_controller_services/run_submission_service.py`
- `src/controller/pipeline_controller_services/history_handoff_service.py`
- `src/controller/pipeline_controller.py`

## Tests

Focused verification passed:

- `pytest tests/gui_v2/test_config_adapter_v26.py tests/controller/test_gui_config_service.py tests/controller/test_history_handoff_service.py tests/controller/test_app_controller_config.py tests/controller/test_app_controller_run_bridge_v2.py tests/controller/test_pipeline_replay_job_v2.py tests/controller/test_app_controller_pipeline_integration.py tests/gui_v2/test_video_workflow_tab_frame_v2.py -q`
- `pytest tests/controller/test_app_controller_pipeline_bridge.py tests/controller/test_app_controller_run_mode_defaults.py tests/controller/test_pipeline_controller_run_modes_v2.py tests/controller/test_controller_event_api_v2.py -q`
- `pytest --collect-only -q -rs` -> `2540 collected / 0 skipped`
- `python -m compileall src/gui/config_adapter_v26.py src/gui/app_state_v2.py src/controller/app_controller_services/gui_config_service.py src/controller/pipeline_controller_services/history_handoff_service.py src/controller/app_controller.py src/controller/pipeline_controller.py src/controller/app_controller_services/run_submission_service.py tests/gui_v2/test_config_adapter_v26.py tests/controller/test_gui_config_service.py tests/controller/test_history_handoff_service.py`

## Deferred Debt

The following still remains intentionally deferred beyond this PR:

- additional controller-size reduction beyond the bounded service extractions in
  this pass
- richer continuity/story-planning exposure on top of the improved video
  workspace
- eventual removal of the `run_config` compatibility projection once all
  remaining GUI consumers stop depending on it
