PR-034-PIPELINE-PRESETS-INTEGRATION-V2-P1
1. Title

PR-034-PIPELINE-PRESETS-INTEGRATION-V2-P1 — Make Pipeline Preset Dropdowns Actually Drive Run Config

2. Summary

Wire the Pipeline preset dropdown in the left column to the actual pipeline run config, backed by ConfigManager and AppStateV2. Selecting a preset should:

Load its saved model/vae/sampler/scheduler/output/batch settings.

Apply them into AppStateV2’s run config.

Push those values into the left column config card UI.

3. Problem Statement

Currently:

There are one or more “Preset” dropdowns in the Pipeline tab that:

Either aren’t wired, or only partially wired, to the actual run config.

Don’t clearly apply to any specific state (pipeline vs prompt).

You already have:

A presets directory with multiple JSON configs.

ConfigManager supporting reading presets.

But selecting a preset in the UI does not reliably:

Update the run config state used by the executor.

Update the UI (model/vae/sampler/output fields).

4. Goals

G1 – Define the pipeline-level preset semantics clearly:

A preset is a saved pipeline run configuration (model/vae/sampler/scheduler/output/batch/seed mode flags).

G2 – Wire the primary Pipeline preset dropdown to:

Load the selected preset via ConfigManager.

Apply its values into AppStateV2’s run config.

Notify PipelineConfigPanelV2 so its fields show the correct values.

G3 – Ensure prompt-pack selection remains independent:

Presets affect how a run executes, not which prompt pack is selected.

G4 – Add tests to ensure preset loading and UI updates don’t regress.

5. Non-goals

Creating or editing presets from the GUI (future PR; for now they are read-only).

Changing the presets file format.

Integrating presets with the learning system or randomizer logic.

Modifying prompt tab behavior.

6. Allowed Files

src/utils/config.py (ConfigManager: preset loading helpers)

src/gui/app_state_v2.py (run config representation)

src/controller/app_controller.py (preset selection handlers)

src/gui/views/sidebar_panel_v2.py (preset dropdown wiring)

src/gui/views/pipeline_config_panel_v2.py (read/write config fields)

Tests:

tests/controller/test_presets_integration_v2.py

tests/gui_v2/test_pipeline_presets_ui_v2.py

7. Forbidden Files

src/gui/main_window_v2.py

Any executor / pipeline runtime logic outside of reading the run config.

Any learning / randomizer modules.

Legacy preset mechanisms in V1 code.

8. Step-by-step Implementation

Define canonical run config schema in AppStateV2:

Ensure there is a clear RunConfig representation:

model_name, vae_name, sampler_name, scheduler_name, steps, cfg_scale, batch_size, seed_mode, output_dir, filename_template.

Add helper methods:

update_from_preset(preset_dict)

to_dict() (if not present).

Extend ConfigManager for preset loading:

Ensure methods like list_presets() and load_preset(name) exist and:

Read from presets directory.

Return a normalized dict matching the run config schema.

Controller wiring in app_controller.py:

Add handler: on_pipeline_preset_selected(preset_name: str).

Load preset from ConfigManager.

Call app_state.run_config.update_from_preset(...).

Notify GUI via existing event/observer or explicit method call.

Sidebar dropdown wiring in sidebar_panel_v2.py:

Ensure there is a single authoritative Pipeline preset dropdown.

Wire its <<ComboboxSelected>> event to on_pipeline_preset_selected.

On initialization:

Populate with ConfigManager.list_presets() results.

Optionally pre-select a default preset if one is marked in config.

Push values into PipelineConfigPanelV2:

Add method apply_run_config(run_config: RunConfig) on PipelineConfigPanelV2 to:

Update the model/vae/sampler/scheduler dropdowns.

Set output directory and filename fields.

Have AppController or AppStateV2 notify the panel when the run config changes (reuse existing app-state observer if present; otherwise a direct call from controller).

Tests:

tests/controller/test_presets_integration_v2.py:

Mock ConfigManager to return a sample preset.

Call on_pipeline_preset_selected("MyPreset").

Assert AppStateV2.run_config updated.

tests/gui_v2/test_pipeline_presets_ui_v2.py:

Build the Pipeline tab.

Simulate selecting a preset from the dropdown.

Assert that config panel fields show expected values (using test preset).

9. Required Tests (Failing first)

tests/controller/test_presets_integration_v2.py

tests/gui_v2/test_pipeline_presets_ui_v2.py

Both should initially fail due to missing handlers or missing calls to update the config panel.

10. Acceptance Criteria

Selecting a preset from the Pipeline preset dropdown:

Updates AppStateV2.run_config fields.

Updates the Pipeline config panel fields to match.

No Tk errors when toggling between presets.

Prompt pack selection remains unchanged when presets change.

11. Rollback Plan

Revert changes to:

config.py

app_state_v2.py

app_controller.py

sidebar_panel_v2.py

pipeline_config_panel_v2.py

Any new tests

This restores previous behavior where presets don’t affect run config.

12. Codex Execution Constraints

No changes to how the executor uses run config; only how run config gets populated.

No I/O beyond preset file reads via ConfigManager.

Avoid heavy refactors; incremental wiring only.

13. Smoke Test Checklist

Launch app.

Open Pipeline tab.

Select a preset from the Pipeline preset dropdown.

Confirm:

Model/vae/sampler/output fields update visibly.

No crashes or errors in terminal logs.