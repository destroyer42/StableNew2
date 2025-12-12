PR-056 — Run Modes & Payload Integration (V2-P1).md
Summary

Run modes (run once, queue, preview) behave inconsistently and do not reliably push config into preview/pipeline. This PR centralizes run-mode state and ensures preview uses the same config that the actual pipeline uses.

Goals

Add a run_mode to AppState.

Bind Pipeline tab run-mode controls to this value.

PipelineController must include run_mode in the config sent downstream.

Preview should reflect the actual config that would run.

Allowed Files

src/gui/views/pipeline_tab_frame_v2.py

src/gui/preview_panel_v2.py

src/gui/app_state_v2.py

src/gui/controller.py

src/controller/pipeline_controller.py

Forbidden Files

Any pipeline executor/runner files

Main entrypoint

Implementation Plan
1. Add run_mode to AppState

Accept values: "run_once", "queue", "preview".

2. Bind GUI controls

Pipeline tab radio buttons or dropdown update app_state.run_mode.

3. Preview integration

Preview panel receives config = pipeline_controller.build_config().

Do not build preview from partial GUI fields.

4. Pipeline config integration

Add:

config["run_mode"] = app_state.run_mode

5. Queue mode

If run_mode = "queue", create a queued job instead of direct execution.

Validation
Tests

tests/controller/test_pipeline_controller_run_mode.py

Given GUI state, assert run_mode → config mapping is correct.

tests/gui_v2/test_pipeline_run_mode_preview.py

Preview receives full config.

Definition of Done

GUI → AppState → config → preview → pipeline are consistent.

No missing run_mode behavior.