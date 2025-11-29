Codex Run Sheet: PR-GUI-V2-MIGRATION-002
Title: Introduce Modular GUI V2 Panels (Pipeline, Randomizer, Preview, Sidebar, Status Bar)

You are implementing PR-GUI-V2-MIGRATION-002 for the StableNew repository. Follow these instructions exactly and do not go out of scope.

1. Scope Guardrails

You MAY modify/create:
- src/gui/main_window.py
- src/gui/pipeline_panel_v2.py
- src/gui/randomizer_panel_v2.py
- src/gui/preview_panel_v2.py
- src/gui/sidebar_panel_v2.py
- src/gui/status_bar_v2.py
- tests/gui_v2/conftest.py
- tests/gui_v2/test_gui_v2_startup.py
- tests/gui_v2/test_gui_v2_layout_skeleton.py
- tests/gui_v2/test_gui_v2_pipeline_button_wiring.py

You MUST NOT modify:
- src/controller/**
- src/pipeline/**
- src/api/**
- src/utils/**
- tests/gui_v1_legacy/**
- Any other tests outside tests/gui_v2/**
- Any CI or tooling configs beyond what is explicitly listed above

If you believe a forbidden file must change, STOP and report instead of editing it.

2. Baseline

Before making any changes, run and capture:
- pytest tests/gui_v2 -v
- pytest -v

Confirm that both complete successfully (with Tk/Tcl skips allowed). This is your starting reference.

3. Implementation Steps

Step A – Create V2 panel modules
1) Create these new files in src/gui/:
   - pipeline_panel_v2.py
   - randomizer_panel_v2.py
   - preview_panel_v2.py
   - sidebar_panel_v2.py
   - status_bar_v2.py

2) In each file, define one ttk.Frame subclass:
   - PipelinePanelV2
   - RandomizerPanelV2
   - PreviewPanelV2
   - SidebarPanelV2
   - StatusBarV2

3) Each panel class should:
   - Call super().__init__(master, **kwargs) in __init__.
   - Accept the following keyword-only parameters:
     - controller
     - theme
     - (PipelinePanelV2 only) config_manager
   - Create a header label (self.header_label) and a body frame (self.body) as child widgets.
   - For StatusBarV2 only, also create:
     - self.status_label
     - self.progress_widget (can be a label or ttk.Progressbar).

4) Do NOT add business logic or pipeline calls. These are structural scaffolds only.

Step B – Integrate panels into StableNewGUI
1) Edit src/gui/main_window.py:
   - Import all new panel classes.
   - In the UI builder (e.g., _build_ui and/or helper methods), instantiate the panels and place them in the layout:
     - SidebarPanelV2 on the left side.
     - PipelinePanelV2 and RandomizerPanelV2 in the center area (using the existing notebook or frames where appropriate).
     - PreviewPanelV2 in the right-hand area.
     - StatusBarV2 at the bottom.

2) Expose panel instances as attributes on StableNewGUI:
   - self.sidebar_panel_v2
   - self.pipeline_panel_v2
   - self.randomizer_panel_v2
   - self.preview_panel_v2
   - self.status_bar_v2

3) Ensure that any existing ConfigPanel usage is not removed in this PR. It may coexist with the new panels; do not attempt full replacement yet.

4) Ensure the primary Run button still calls the controller’s start/run method (as it did before). If necessary, expose the button as self.run_button for tests.

Step C – Update GUI V2 tests

1) tests/gui_v2/test_gui_v2_startup.py
   - Confirm StableNewGUI can be instantiated when Tk is available.
   - Skip tests cleanly if Tk/Tcl is not available (reuse the existing pattern from API status panel tests).

2) tests/gui_v2/test_gui_v2_layout_skeleton.py
   - Import the V2 panel classes.
   - Instantiate StableNewGUI.
   - Assert:
     - isinstance(gui.sidebar_panel_v2, SidebarPanelV2)
     - isinstance(gui.pipeline_panel_v2, PipelinePanelV2)
     - isinstance(gui.randomizer_panel_v2, RandomizerPanelV2)
     - isinstance(gui.preview_panel_v2, PreviewPanelV2)
     - isinstance(gui.status_bar_v2, StatusBarV2)

3) tests/gui_v2/test_gui_v2_pipeline_button_wiring.py
   - Monkeypatch PipelineController with a dummy class that records calls to its start method (or equivalent).
   - Stub out any webui auto-launch and messagebox behavior to avoid side effects.
   - Instantiate StableNewGUI.
   - Locate the Run button (using gui.run_button or an equivalent stable handle).
   - Simulate a click on the Run button.
   - Assert that the dummy controller’s start method was called exactly once.

Step D – Headless/test-mode behavior (if needed)

1) If GUI V2 tests fail due to WebUI auto-launch or discovery side effects, reuse the existing GUI test mode flag pattern (e.g., STABLENEW_GUI_TEST_MODE or STABLENEW_V2_GUI_TEST_MODE) already used elsewhere.
2) Only add a new environment check in main_window.py if absolutely necessary, and only to short-circuit side effects in tests.
3) Do not change runtime behavior for normal users when the env var is not set.

4. Test Execution Order

After implementing the steps above, run and capture the full output of:

1) pytest tests/gui_v2 -v
2) pytest -v

These must pass (Tk/Tcl skips are acceptable) before you consider the PR complete.

5. Success Criteria

You are done when:
- The five new panel classes exist and are importable.
- StableNewGUI exposes sidebar_panel_v2, pipeline_panel_v2, randomizer_panel_v2, preview_panel_v2, and status_bar_v2.
- tests/gui_v2/startup, layout, and pipeline-button tests all pass.
- pytest tests/gui_v2 -v passes.
- pytest -v passes, with GUI V2 tests included and no legacy GUI import explosions.
- No forbidden files were modified.

Do not expand the scope of this PR beyond what is described here.
