Codex Run Sheet: PR-GUI-V2-MIGRATION-003
Title: Wire PipelinePanelV2 to Real Pipeline Config Behavior

You are implementing PR-GUI-V2-MIGRATION-003 for the StableNew repository. Follow these instructions exactly and stay in scope.

1. Scope Guardrails

You MAY modify/create:
- src/gui/pipeline_panel_v2.py
- src/gui/main_window.py
- tests/gui_v2/conftest.py
- tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py
- tests/gui_v2/test_gui_v2_pipeline_button_wiring.py

You MUST NOT modify:
- src/controller/**
- src/pipeline/**
- src/api/**
- src/utils/**
- tests/gui_v1_legacy/**
- Any tests outside tests/gui_v2/**
- Any CI/tooling configs not explicitly listed above

If you think a forbidden file must change, STOP and report instead of editing it.

2. Baseline

Before any edits, run and capture:
- pytest tests/gui_v2 -v
- pytest -v

These give you the pre-PR baseline from PR-GUI-V2-MIGRATION-002.

3. Implementation Steps

Step A – Enhance PipelinePanelV2

1) Open src/gui/pipeline_panel_v2.py.

2) Choose a minimal set of core pipeline fields to support in this PR (txt2img focus):
   - model
   - vae
   - sampler_name
   - scheduler
   - steps
   - cfg_scale
   - width
   - height

3) For each field, ensure PipelinePanelV2 has:
   - A backing tk variable (e.g., StringVar/IntVar/DoubleVar).
   - A widget (Entry/Spinbox/Combobox) bound to that variable.
   - Stable attributes so tests can find them (e.g., self.steps_var, self.steps_entry, etc.).

4) Add two methods to PipelinePanelV2:
   - def load_from_config(self, config: dict[str, object]) -> None
     - Read the eight fields from the provided config dict (respecting existing nesting such as config["txt2img"]["steps"], etc.).
     - Populate the backing tk variables with sensible defaults if keys are missing.
   - def to_config_delta(self) -> dict[str, object]
     - Return a dict containing only the fields the panel owns, under the appropriate nesting (e.g., {"txt2img": {...}}).
     - Do NOT include unrelated fields.

5) Optionally define small, private helpers to keep mapping logic tidy:
   - _get_txt2img_section(config: dict) -> dict
   - _build_txt2img_delta(...) -> dict
   Keep them local to this module.

Step B – Connect the panel to StableNewGUI’s config lifecycle

1) Open src/gui/main_window.py.

2) Find where StableNewGUI obtains its initial config (via ConfigManager or similar). After that config is available and after PipelinePanelV2 is instantiated:
   - Call self.pipeline_panel_v2.load_from_config(effective_config).

3) Find the path where the GUI starts the pipeline (the method that ultimately calls into PipelineController / PipelineRunner).
   Just before the config is passed to the controller/pipeline:
   - Obtain the base config dict as usual.
   - Call delta = self.pipeline_panel_v2.to_config_delta().
   - Merge delta into the base config, overriding only the keys owned by PipelinePanelV2.
   - Pass the merged config to the controller/pipeline as you do now.

4) Do NOT change any controller or pipeline APIs. Only adjust the config dict values passed in.

Step C – Test fixtures (DummyController / DummyConfigManager)

1) Open tests/gui_v2/conftest.py.

2) If not already present, define:
   - DummyConfigManager
     - Returns a stable base config dict that includes txt2img with the eight fields above.
     - Implements only the methods StableNewGUI actually calls (inspect main_window.py to know which).
   - DummyController
     - Provides the method that StableNewGUI calls to start the pipeline (e.g., run_full_pipeline, start_pipeline, etc.).
     - Records the last config dict passed, e.g., self.last_run_config.

3) Provide pytest fixtures to supply these into StableNewGUI, for example:
   - @pytest.fixture
     def gui_with_dummy_controller(...):
         # Build StableNewGUI using DummyController and DummyConfigManager.

Step D – New GUI V2 tests

1) tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py (new)

Create tests that do the following:

- Startup roundtrip:
  - Use the fixtures to instantiate StableNewGUI.
  - After creation, inspect gui.pipeline_panel_v2’s fields (steps, cfg, etc.).
  - Assert they match the initial DummyConfigManager config values.

- Run roundtrip:
  - Instantiate StableNewGUI via fixtures.
  - Modify gui.pipeline_panel_v2’s tk variables (e.g., set steps to a different value, change width/height, change model, etc.).
  - Trigger the Run action by invoking the same command a user would (e.g., calling gui.run_button.invoke()).
  - Assert:
    - DummyController was called exactly once.
    - The config dict that DummyController saw includes the updated values for model, vae, sampler_name, scheduler, steps, cfg_scale, width, and height under the correct keys.

2) tests/gui_v2/test_gui_v2_pipeline_button_wiring.py

- Keep this test focused on verifying that clicking the Run button results in a controller call.
- Update it to reuse DummyController if needed, but do NOT duplicate roundtrip config assertions here (that’s the job of the new test file).

Step E – Headless-safety

1) For any test that creates a Tk root:
   - Wrap tk.Tk() in a try/except tk.TclError.
   - If Tk is unavailable, call pytest.skip with a clear message.
2) Do NOT introduce new environment flags unless absolutely necessary.

4. Test Execution Order

After implementing the changes above, run and capture full output of:

1) pytest tests/gui_v2 -v
2) pytest -v

Both must pass (Tk/Tcl skips allowed). If any new failures appear, fix them within this PR scope.

5. Success Criteria

You are done when:

- PipelinePanelV2:
  - Can load from a config dict.
  - Emits a delta dict via to_config_delta() that reflects the visible field values.
- StableNewGUI:
  - Calls load_from_config() on startup.
  - Merges to_config_delta() into the base pipeline config before starting a run.
- tests/gui_v2:
  - Contain a passing startup-roundtrip test.
  - Contain a passing run-roundtrip test validating config propagation to DummyController.
  - Still include a working Run-button wiring test.
- pytest tests/gui_v2 -v passes.
- pytest -v passes with GUI V2 tests included and no new GUI import errors.
- No forbidden files were modified.

Do not expand beyond this scope.
