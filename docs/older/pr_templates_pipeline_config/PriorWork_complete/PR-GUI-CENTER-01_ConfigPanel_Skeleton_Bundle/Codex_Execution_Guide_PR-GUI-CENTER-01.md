Codex Execution Guide for PR-GUI-CENTER-01: Core Config Panel Skeleton
======================================================================

Purpose
-------
You are implementing PR-GUI-CENTER-01 to add a basic Config Panel to the Center Zone of the v2 GUI. The panel will expose core SD settings (model, sampler, resolution, steps, CFG) and keep them in `AppController` state, without changing the pipeline calls yet.

Scope
-----
You may only modify/create:

- `src/controller/app_controller.py`
- `src/gui/main_window_v2.py`
- `src/gui/config_panel.py` (new)
- New tests:
  - `tests/controller/test_app_controller_config.py`
  - `tests/gui/test_config_panel.py`

Implementation Steps
--------------------
1. Add simple config state to AppController (model, sampler, width, height, steps, cfg_scale) plus helper methods `get_available_models()`, `get_available_samplers()`, `get_current_config()`, and `update_config(**kwargs)`.
2. Create a `ConfigPanel(ttk.Frame)` in `src/gui/config_panel.py` with controls for model, sampler, resolution, steps, and CFG, plus a `refresh_from_controller(...)` method.
3. Wire ConfigPanel into the Center Zone in `MainWindow_v2`, and route change events to `AppController.update_config(...)` via methods on the window.
4. Add tests:
   - Controller config tests in `tests/controller/test_app_controller_config.py`.
   - Basic ConfigPanel tests in `tests/gui/test_config_panel.py`.
5. Run:
   - `pytest tests/controller/test_app_controller_config.py -v`
   - `pytest tests/gui/test_config_panel.py -v`
   - `pytest tests/controller/test_app_controller_pipeline_flow_pr0.py -v`
   and ensure all pass.
