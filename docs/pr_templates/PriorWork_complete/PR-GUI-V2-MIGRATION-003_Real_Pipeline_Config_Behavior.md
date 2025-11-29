PR ID: PR-GUI-V2-MIGRATION-003
Title: Wire PipelinePanelV2 to Real Pipeline Config Behavior

1. Summary
This PR makes the GUI V2 pipeline panel do real work.

Right now PipelinePanelV2 is a structural shell. The underlying pipeline still relies on legacy configuration flows, and changing fields in the V2 area does not have a clearly defined, tested relationship to the effective pipeline configuration.

This PR wires PipelinePanelV2 into the existing ConfigManager / StableNewGUI plumbing so that:
- The panel reflects the current pipeline configuration on startup.
- Edits in the panel update a concrete in-memory config structure used when the Run button is pressed.
- The controller receives a config that matches the values the user sees in the GUI.

All of this is done within the GUI layer only, using existing ConfigManager behavior, without touching controller/pipeline business logic.

2. Problem Statement
After PR-GUI-V2-MIGRATION-001 and -002, we have:
- A clean GUI V2 test harness (tests/gui_v2/**) that exercises StableNewGUI startup and basic wiring.
- Modular V2 panels (PipelinePanelV2, RandomizerPanelV2, PreviewPanelV2, SidebarPanelV2, StatusBarV2) mounted into StableNewGUI.

However, the pipeline panel is still mostly cosmetic:
- It does not reliably load the current pipeline-related configuration into the visible controls.
- Changes made in the panel are not clearly or testably propagated into the configuration used when the pipeline runs.
- There is no focused, minimal test coverage that says: “when I set steps/CFG/width/height/model/sampler in the V2 panel and press Run, the controller sees those same values in the pipeline config.”

This gap blocks meaningful V2 pipeline UX work: we cannot safely iterate on “smart defaults”, presets, or simplification while the panel is not the single source of truth for what the user is asking the pipeline to do.

3. Goals
- Make PipelinePanelV2 the primary GUI surface for core pipeline settings (at least for txt2img) in the V2 layout.
- On GUI startup:
  - Read the effective pipeline config (via ConfigManager or the same source StableNewGUI already uses).
  - Populate the PipelinePanelV2 fields from that config.
- On user edits:
  - Keep an in-memory representation of the V2 pipeline config that is consistent with the visible fields.
  - Provide a simple method to retrieve that config when the pipeline is about to run.
- On Run button press:
  - Ensure StableNewGUI passes a config to the controller/pipeline whose core fields match what is in PipelinePanelV2.
- Add tests under tests/gui_v2 that:
  - Drive a StableNewGUI instance (with a dummy controller + dummy config manager).
  - Programmatically set V2 pipeline fields (steps, cfg_scale, width, height, sampler, scheduler, model, vae).
  - Trigger the Run action.
  - Assert that the dummy controller receives a config dict with matching values.
- Respect Architecture_v2: GUI owns layout and user interaction; controller/pipeline stay unchanged.

4. Non-goals
- No changes to controller behavior, PipelineRunner, or run_full_pipeline.
- No changes to ConfigManager’s public API or on-disk file format.
- No changes to randomizer/matrix logic or sanitization behavior.
- No changes to legacy GUI v1 behavior or tests under tests/gui_v1_legacy/**.
- No new “smart” defaults, presets, or UX flows beyond what is needed to make V2 reflect and push the basic config fields.
- No ADetailer, refiner, or advanced options in this PR; keep scope to a small, high-value subset of pipeline parameters.

5. Allowed Files
Codex may modify or create ONLY the following paths:

GUI:
- src/gui/pipeline_panel_v2.py
- src/gui/main_window.py

Tests:
- tests/gui_v2/conftest.py
- tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py (new)
- tests/gui_v2/test_gui_v2_pipeline_button_wiring.py (may be adjusted to accommodate new config plumbing)

Docs (optional, if you commit them):
- docs/pr_templates/PR-GUI-V2-MIGRATION-003_Real_Pipeline_Config_Behavior.md
- docs/pr_templates/Codex_Run_Sheet_PR-GUI-V2-MIGRATION-003.md

6. Forbidden Files
Codex MUST NOT modify:
- src/controller/**
- src/pipeline/**
- src/api/**
- src/utils/**
- tests/gui_v1_legacy/**
- Any tests outside tests/gui_v2/**
- CI configs, tools, or scripts not explicitly listed above

If a change appears necessary in a forbidden file, STOP and report instead of editing it. That would be a new PR.

7. Step-by-step Implementation

Step 1 – Decide the core fields for this PR
Within PipelinePanelV2, support a minimal but meaningful subset of txt2img pipeline parameters:

- model
- vae
- sampler_name
- scheduler
- steps
- cfg_scale
- width
- height

These fields must:
- Be readable from the initial config object (coming from ConfigManager or equivalent).
- Be editable via simple tk/ttk widgets (Entry/Spinbox/Combobox).
- Be included in the outbound config that is handed to the controller’s pipeline call.

Step 2 – Introduce a simple PipelineUIConfig adapter in the panel
In src/gui/pipeline_panel_v2.py:

1) Add a small, GUI-local helper (not exported outside the module) to translate between a config dict and the panel fields, for example:

- A @dataclass PipelineUIConfig living inside this module, OR
- Two pure functions:
  - _extract_pipeline_ui_config(raw_config: dict) -> dict[str, Any]
  - _apply_pipeline_ui_to_config(ui_values: dict[str, Any], base_config: dict) -> dict[str, Any]

Constraints:
- Keep this localized to the GUI module; do not move it to utils or pipeline.
- Do not change underlying config semantics; just map to/from the existing dict structure.

2) Add methods on PipelinePanelV2:
- def load_from_config(self, config: dict[str, Any]) -> None
  - Reads the relevant fields from config and populates the widgets (with appropriate defaults if keys are missing).
- def to_config_delta(self) -> dict[str, Any]
  - Returns a small dict containing only the fields that the panel owns (e.g., nested under "txt2img" if that is how ConfigManager structures it).

The exact key paths should mirror the existing config layout (inspect how ConfigManager and ConfigPanel represent txt2img pipeline options).

Step 3 – Wire the panel to StableNewGUI’s config lifecycle
In src/gui/main_window.py:

1) On GUI construction or in _build_ui (after ConfigManager is available):
- Obtain the current effective config dict using the same method StableNewGUI already uses to populate ConfigPanel / default state.
- Call self.pipeline_panel_v2.load_from_config(effective_config).

2) Before starting the pipeline (i.e., just before controller.start/run is invoked):
- Obtain the base config dict that will be used to run the pipeline (same as now).
- Call delta = self.pipeline_panel_v2.to_config_delta().
- Merge that delta into the base config in a non-destructive way:
  - Only override the fields the panel owns.
  - Leave everything else unchanged.
- Pass the merged config to the controller/pipeline as you do today.

Important:
- Do NOT change how CancelToken or lifecycle events are handled.
- Do NOT alter any controller or pipeline APIs; only adjust what config dict is passed.

Step 4 – Make the controller visible to PipelinePanelV2 only where needed
PipelinePanelV2’s constructor already receives controller and config_manager hooks. In this PR, keep things simple:

- For now, do not call controller methods directly from the panel; treat it as “config-focused”. The controller remains orchestrated by StableNewGUI.
- Use config_manager if necessary to get defaults (for example, a “default config” dict), but do not change ConfigManager implementation.
- If ConfigManager already offers a “current config” or “defaults” helper, prefer that.

If you find you do not need the controller reference inside PipelinePanelV2 for this PR, leave it unused (but do not remove it; we will use it in later PRs).

Step 5 – Extend the GUI V2 tests

1) tests/gui_v2/conftest.py
- If not already present, define a DummyController and DummyConfigManager suitable for GUI tests:
  - DummyController:
    - Records the last config passed to start_pipeline / run_full_pipeline / whatever method StableNewGUI calls (you may need to inspect main_window.py to know the exact method name).
  - DummyConfigManager:
    - Provides a deterministic base config dict that includes the txt2img fields listed in Step 1.
    - Either mimic the real ConfigManager interface or mock just the methods StableNewGUI actually calls.

2) tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py (new)
- Scenario: “V2 pipeline panel reflects and drives config”

  - Arrange:
    - Use the DummyConfigManager and DummyController from conftest.py.
    - Instantiate StableNewGUI with these injected (whatever constructor path is used today in tests/gui_v2).
  - Act:
    - Locate gui.pipeline_panel_v2.
    - Programmatically set widget values for steps, cfg_scale, width, height, sampler_name, scheduler, model, vae.
    - Trigger the Run action through the same path a user would (e.g., click gui.run_button or invoke the bound command).
  - Assert:
    - The DummyController was called exactly once.
    - The config dict it received has the specified values for the core fields, under the correct keys/nesting (txt2img or similar).

- Also add a test that checks startup behavior:
  - After GUI creation, the panel fields should match the initial DummyConfigManager config (steps, cfg, etc.).

3) tests/gui_v2/test_gui_v2_pipeline_button_wiring.py
- Keep this test focused on “button calls controller” with as few assumptions as possible.
- If necessary, update it to reuse the same DummyController from conftest.py and to be compatible with the new config handling, but do not over-assert on the config (that’s the job of the new roundtrip test).

Step 6 – Headless safety
- Continue using the same Tk/Tcl skip pattern used elsewhere (e.g., try tk.Tk(), except tk.TclError -> pytest.skip).
- Do not introduce new environment flags in this PR unless strictly required to avoid side effects.
- If you must re-use STABLENEW_GUI_TEST_MODE or similar, do so in a way that affects only tests and not normal runtime behavior.

8. Required Tests (Failing First)
Before making any changes, run and capture:

- pytest tests/gui_v2 -v
- pytest -v

Expect these to be passing (or skipping Tk-dependent tests) from the state after PR-GUI-V2-MIGRATION-002.

After implementing this PR, iterate until the following both pass:

- pytest tests/gui_v2 -v
- pytest -v

Any new failures in tests/gui_v2 must be resolved within this PR; failures in other suites that predate this PR should be called out explicitly in your summary.

9. Acceptance Criteria
This PR is complete when:

- PipelinePanelV2:
  - Can load its fields from a config dict.
  - Can emit a delta dict representing the fields it owns.
- StableNewGUI:
  - Calls PipelinePanelV2.load_from_config(...) after building the UI.
  - Calls PipelinePanelV2.to_config_delta() just before starting the pipeline and merges that delta into the base config dict sent to the controller.
- tests/gui_v2:
  - Include a new pipeline config roundtrip test that:
    - Sets V2 panel fields.
    - Triggers Run.
    - Confirms the controller sees matching config values.
  - Continue to include the startup and button wiring tests, which still pass.
- pytest tests/gui_v2 -v passes (with only Tk/Tcl skips allowed).
- pytest -v completes without new GUI import explosions and with the updated GUI V2 tests in the summary.
- No forbidden files have been modified.

10. Rollback Plan
If this PR needs to be rolled back:

- Revert changes in:
  - src/gui/pipeline_panel_v2.py
  - src/gui/main_window.py
  - tests/gui_v2/conftest.py
  - tests/gui_v2/test_gui_v2_pipeline_config_roundtrip.py
  - tests/gui_v2/test_gui_v2_pipeline_button_wiring.py
- Confirm that:
  - PipelinePanelV2 returns to being a mostly structural shell.
  - The previous GUI V2 tests (post PR-GUI-V2-MIGRATION-002) pass:
    - pytest tests/gui_v2 -v
    - pytest -v

11. Codex Execution Constraints
- Keep changes small and clearly scoped to GUI V2 and its tests.
- Do not modify any controller, pipeline, or utils files.
- Do not introduce new business logic into the GUI beyond straightforward config field mapping and merging.
- Prefer clear, explicit attribute names and helper methods; avoid complex abstraction layers.
- Always paste the full output of:
  - pytest tests/gui_v2 -v
  - pytest -v
  in your final PR message.

12. Smoke Test Checklist
Before declaring success, verify:

- StableNewGUI still starts in the V2 harness.
- PipelinePanelV2 fields reflect the DummyConfigManager initial config in tests.
- Editing panel fields, then pressing Run, results in the DummyController receiving a config dict with matching values for:
  - model
  - vae
  - sampler_name
  - scheduler
  - steps
  - cfg_scale
  - width
  - height
- All tests under tests/gui_v2 pass.
- The full pytest run passes (with any pre-existing, non-GUI issues clearly identified if they still exist).
