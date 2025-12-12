PR-081D-4 — RunConfig Refiner-Hires Fields + Controller/GUI Wiring (No Sequencing Changes)

Intent
Introduce missing refiner and hires-fix fields into RunConfig, AppState, AppController config assembly, and PipelineConfigPanel/StageCards.
This makes the data model complete so that GUI V2 and controller tests stop failing on:

AttributeError: 'RunConfig' object has no attribute 'refiner_enabled'


But does NOT change sequencing (ADetailer/refiner ordering is PR-081D-5+ territory).

Summary of Failures Addressed

Failures include:

Controller config tests

GUI stage-card wiring tests

Main window smoke test

Pipeline tab wiring tests

Journey tests initializing RunConfig

Errors:

AttributeError: 'RunConfig' object has no attribute 'refiner_enabled'


Indicates the config model is incomplete relative to GUI V2 StageCards and updated test suite.

Scope & Risk

Risk: Medium
Subsystems: Controller config / GUI state only
No sequencing changes permitted.
No executor/pipeline changes allowed.

Files Allowed to Modify
src/gui/state.py           (RunConfig dataclass)
src/gui/app_state_v2.py    (if storing these fields)
src/controller/app_controller.py  (config assembly/apply_config)
src/gui/panels_v2/pipeline_config_panel_v2.py
src/gui/stage_cards_v2/*   (refiner/hires toggles)
src/gui/pipeline_command_bar_v2.py (if reading RunConfig)
tests/controller/test_app_controller_config.py
tests/gui_v2/*config* tests

Forbidden Files
src/pipeline/executor.py
src/pipeline/stage_sequencer.py
src/pipeline/run_plan.py
src/pipeline/pipeline_runner.py
src/gui/main_window_v2.py
src/main.py

Implementation Plan
1. Extend RunConfig with missing refiner/hires fields

Add fields:

refiner_enabled: bool = False
refiner_model_name: str | None = None

# Hires fields (txt2img/img2img)
enable_hr: bool = False
hr_scale: float = 2.0
hr_upscaler: str = "Latent"
hr_second_pass_steps: int = 0
hr_resize_x: int = 0
hr_resize_y: int = 0
denoising_strength: float = 0.7
hr_sampler_name: str | None = None


These reflect the executor’s existing payload structure.

2. Mirror these fields in GUI State (app_state_v2)

AppState must store these fields so GUI V2 stage cards can bind to them:

self.refiner_enabled
self.refiner_model_name
...

3. Update AppController’s config assembly

Modify:

get_current_config()

apply_config()

assemble_run_config_from_state()

To include the new fields, reading/writing them from stage cards.

4. Update PipelineConfigPanelV2 and stage cards

Minimal wiring so each stage card exposes:

Refiner toggle (Enable Refiner)

Refiner model dropdown

Hires-fix toggles/sliders

This PR does not enforce sequencing or visibility logic, only exposes fields.

5. Update DummyPipelineController or test stubs

Any tests referencing:

controller.get_current_config().refiner_enabled


must receive a fully-populated RunConfig.

6. Ensure last-run restore stores/loads these fields

If relevant in:

src/pipeline/last_run_store_v2_5.py


Expose fields without sequencing.

7. Update tests

Fix expected config dicts in:

test_app_controller_config.py

All GUI wiring tests that assert field existence

Acceptance Criteria
✔ RunConfig exposes full refiner + hires fields
✔ Controller config tests pass
✔ GUI V2 wiring tests pass (no AttributeErrors)
✔ Journey tests that create RunConfig no longer fail at construction
✔ No change to sequencing logic, ADetailer ordering, or executor behavior
✔ GUI toggles/sliders appear but do not enforce processing order yet
Validation Checklist

App boots normally

GUI V2 pipeline tab loads without missing attributes

Dropdown population unaffected

No pipeline execution changes

Only app-state and controller-config paths changed

No forbidden files modified

🚀 Deliverables

Updated RunConfig dataclass

Updated AppState + AppController config read/write paths

Updated stage cards to surface refiner/hires config fields

Updated tests to match new config model

All config wiring tests green