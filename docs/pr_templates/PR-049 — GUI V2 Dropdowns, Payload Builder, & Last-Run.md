PR-049 — GUI V2 Dropdowns, Payload Builder, & Last-Run Restore (Updated)
Purpose: unify dropdown population, deterministic payload building, and last-run persistence so that the GUI produces correct, pipeline-ready configs every time.
1. Summary

The V2 GUI currently displays controls but dropdowns aren’t consistently populated, payload construction is inconsistent, and last-run restore is incomplete. These three concerns must be unified and stabilized.

This PR introduces:

A consistent dropdown loader, using WebUI resources & config defaults.

A deterministic payload builder, converting AppState → PipelineConfig → executor_config.

A reliable last-run restore mechanism that fully restores:

Model

Sampler

Steps

Sizes

Stage toggles

ADetailer (once PR-034C lands)

Upscale options

Seed / randomize state

This PR does not introduce new features; it stabilizes the backbone of end-to-end execution.

2. Allowed Files

GUI & State

src/gui/app_state_v2.py

src/gui/views/pipeline_tab_frame_v2.py

src/gui/panels_v2/stage_cards_panel_v2.py

src/gui/stage_cards_v2/* (only for load/export helpers)

src/gui/dropdown_loader_v2.py (NEW)

Controller

src/controller/app_controller.py

src/controller/webui_connection_controller.py

Pipeline

src/pipeline/pipeline_runner.py (payload builder path only)

Config

src/utils/config.py (only for last-run file path / load / save helpers)

3. Forbidden Files

src/pipeline/executor.py

src/pipeline/stage_sequencer.py

src/gui/main_window_v2.py

src/api/* beyond WebUI resource fetch

4. Implementation Details
4.1 Dropdown Loader (NEW)

Create dropdown_loader_v2.py:

Consumes WebUI resources + ConfigManager defaults

Emits dict:

{
  "models": [...],
  "vae": [...],
  "samplers": [...],
  "schedulers": [...],
  "adetailer_models": [...],  # populated after PR-034D
  ...
}


Methods:

load_dropdowns(controller, app_state)

apply_to_gui(pipeline_tab, stage_cards_panel)

4.2 Payload Builder Unification

In app_controller.py:

Add method build_pipeline_config_v2():

Reads all AppState entries

Produces PipelineConfig(...)

Passes it to PipelineRunner._build_executor_config()

Ensures:

No missing fields

No mismatched types

All stage toggles honored

4.3 Last-Run Restore

Add:

config.write_last_run(executor_config)

config.load_last_run()

Restore:

All dropdown values

Card values

Toggles

Seed + randomization mode

Everything needed to reproduce a previous run

4.4 UI Wiring

Pipeline tab:

Add “Restore Last Run” button

Automatically call restore on startup if config exists

5. Tests

Add:

tests/gui_v2/test_dropdown_population_v2.py

tests/controller/test_payload_build_v2.py

tests/controller/test_last_run_restore_v2.py

6. Definition of Done

Dropdown population unified and correct.

Payload always builds correctly → executor config.

Last-run restore works fully.

No regressions in pipeline execution.