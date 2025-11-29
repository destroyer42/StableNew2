PR ID: PR-GUI-V2-MIGRATION-002
Title: Introduce Modular GUI V2 Panels (Pipeline, Randomizer, Preview, Sidebar, Status Bar)

1. Summary
This PR introduces the first real modular GUI V2 panel set and wires it into the existing StableNewGUI main window in a minimal, test-driven way. It creates dedicated V2 panel classes for pipeline configuration, randomization, preview, sidebar, and status bar, and updates the GUI V2 test harness to validate layout and controller wiring.

The goal is to move away from the monolithic ConfigPanel/layout and toward the modular Architecture_v2 design, while keeping behavior changes small and fully covered by the new tests in tests/gui_v2.

2. Problem Statement
After PR-GUI-V2-MIGRATION-001, we now have:
- Legacy GUI tests archived under tests/gui_v1_legacy (non-blocking).
- A functional GUI V2 harness in tests/gui_v2 that exercises StableNewGUI startup and basic wiring.

However, the current GUI implementation remains largely monolithic:
- Core responsibilities for pipeline configuration, randomization, and preview are still entangled.
- Layout is not yet organized into clean, composable panels as envisioned by Architecture_v2.
- Adding new features or simplifying user journeys is difficult without a modular structure.

We need to introduce a clear, modular panel architecture (PipelinePanelV2, RandomizerPanelV2, PreviewPanelV2, SidebarPanelV2, StatusBarV2) and ensure it is safely wired, test-covered, and ready for incremental enhancement.

3. Goals
- Introduce explicit V2 panel classes under src/gui for:
  - Pipeline configuration
  - Randomization settings
  - Image preview
  - Sidebar (packs/lists/navigation)
  - Status bar (progress + textual status)
- Update StableNewGUI to host these panels in a clean, discoverable layout consistent with the GUI V2 harness.
- Extend tests/gui_v2 to assert the presence and wiring of these panels (without overspecifying pixels or theme details).
- Keep behavior changes minimal and focused on layout/composition, not on pipeline execution or complex business logic.
- Maintain headless-safe behavior using the existing test-mode patterns where needed.

4. Non-goals
- No changes to controller, pipeline, or API behavior.
- No new randomizer or matrix logic, and no changes to sanitization behavior.
- No new configuration management semantics (ConfigManager stays as-is for now).
- No changes to legacy GUI v1 tests or behavior.
- No attempt to fully replace ConfigPanel functionality; this PR is about introducing modular V2 panels and integrating them into the main window, not about removing the old panel’s detailed controls.

5. Allowed Files
Codex may modify or create ONLY the following paths in this PR:
- src/gui/main_window.py
- src/gui/pipeline_panel_v2.py (new)
- src/gui/randomizer_panel_v2.py (new)
- src/gui/preview_panel_v2.py (new)
- src/gui/sidebar_panel_v2.py (new)
- src/gui/status_bar_v2.py (new)
- tests/gui_v2/conftest.py
- tests/gui_v2/test_gui_v2_startup.py
- tests/gui_v2/test_gui_v2_layout_skeleton.py
- tests/gui_v2/test_gui_v2_pipeline_button_wiring.py
- docs/pr_templates/PR-GUI-V2-MIGRATION-002_Introduce_Modular_GUI_V2_Panels.md (this PR doc, if checked in)
- docs/pr_templates/Codex_Run_Sheet_PR-GUI-V2-MIGRATION-002.md (optional run sheet, if committed)

6. Forbidden Files
Codex MUST NOT modify:
- src/controller/**
- src/pipeline/**
- src/api/**
- src/utils/**
- Any tests outside tests/gui_v2/**
- Any CI configs, tools, or scripts other than the allowed GUI test files above
- tests/gui_v1_legacy/** (legacy suite remains archived and untouched)

If a change appears necessary in any forbidden area, Codex must stop and report the need for a new PR.

7. Step-by-step Implementation

Step 1 – Define the V2 panel modules
Create the following new modules under src/gui:

1. src/gui/pipeline_panel_v2.py
   - Define a class PipelinePanelV2(ttk.Frame):
     - Constructor signature: __init__(self, master, *, controller, config_manager, theme, **kwargs)
     - Minimal responsibilities for this PR:
       - Create a labeled container for pipeline configuration (e.g., a frame with a header label and a placeholder body).
       - Expose a small, stable surface for tests:
         - self.header_label (tk/ttk Label)
         - self.body (ttk.Frame or similar)
     - No real config editing logic yet; this is a structural scaffold.

2. src/gui/randomizer_panel_v2.py
   - Define RandomizerPanelV2(ttk.Frame):
     - Constructor: __init__(self, master, *, controller, theme, **kwargs)
     - Minimal responsibilities:
       - A labeled container for randomization/matrix controls.
       - Stable attributes for tests, e.g.:
         - self.header_label
         - self.body

3. src/gui/preview_panel_v2.py
   - Define PreviewPanelV2(ttk.Frame):
     - Constructor: __init__(self, master, *, controller, theme, **kwargs)
     - Minimal responsibilities:
       - A placeholder preview area with a header and body container for future image previews.
       - Stable attributes: header_label, body.

4. src/gui/sidebar_panel_v2.py
   - Define SidebarPanelV2(ttk.Frame):
     - Constructor: __init__(self, master, *, controller, theme, **kwargs)
     - Minimal responsibilities:
       - A left-hand sidebar container that will eventually host packs, lists, and navigation elements.
       - For now, just a labeled section and a body frame.
       - Stable attributes: header_label, body.

5. src/gui/status_bar_v2.py
   - Define StatusBarV2(ttk.Frame):
     - Constructor: __init__(self, master, *, controller, theme, **kwargs)
     - Minimal responsibilities:
       - A bottom status bar with:
         - A status label (e.g., “Ready”)
         - A progress indicator (could be a ttk.Progressbar or a simple label for this PR)
       - Stable attributes:
         - self.status_label
         - self.progress_widget (label or progressbar)
     - No lifecycle or pipeline callbacks yet; wiring will be handled in later PRs.

All panel classes should:
- Use tk/ttk only (no controller/pipeline logic embedded inside).
- Respect the existing theme module where possible (e.g., background/foreground colors via Theme/ASWF_* tokens), without introducing new theme dependencies.

Step 2 – Integrate panels into StableNewGUI layout
Modify src/gui/main_window.py to:
1. Import the new V2 panel classes.
2. In _build_ui (or the appropriate layout-builder methods), instantiate and place the panels using the modular layout pattern:
   - SidebarPanelV2 in the left pane.
   - PipelinePanelV2 and RandomizerPanelV2 in the central notebook area (e.g., separate tabs or vertically stacked sections on a “Pipeline” tab, depending on existing layout constraints).
   - PreviewPanelV2 in the right pane (or a dedicated area consistent with the current scaffold).
   - StatusBarV2 at the bottom of the main window.
3. Expose stable attributes on StableNewGUI so tests can find the panels:
   - self.sidebar_panel_v2
   - self.pipeline_panel_v2
   - self.randomizer_panel_v2
   - self.preview_panel_v2
   - self.status_bar_v2
4. Continue to observe the Architecture_v2 rule that the GUI layer owns layout and delegates behavior to the controller; do not introduce any new business logic in the GUI.

If any legacy ConfigPanel usage is still present, ensure it coexists with the new panels for now rather than being removed. Full replacement will occur in a future PR.

Step 3 – Wire the Run button to the controller via V2 panels (lightly)
Within src/gui/main_window.py:
1. Identify the primary “Run Full Pipeline” button (or equivalent).
2. Ensure that, in the V2 layout, this button still calls the controller’s start/run method as expected.
   - This may already be true; in that case, confirm that the refactored layout still exposes the button and its callback in a way that tests can exercise.
3. If necessary, expose a stable attribute for the button in StableNewGUI for tests, e.g.:
   - self.run_button

Do NOT introduce new controller methods or change pipeline behavior; just preserve the existing wiring under the new layout.

Step 4 – Extend GUI V2 tests
Update tests/gui_v2 to validate the new panels and wiring:

1. tests/gui_v2/test_gui_v2_startup.py
   - Confirm that StableNewGUI can be instantiated without error (with Tk available).
   - Skip tests cleanly if Tk/Tcl is not available.

2. tests/gui_v2/test_gui_v2_layout_skeleton.py
   - Assert the presence and type of V2 panels:
     - gui.sidebar_panel_v2 is an instance of SidebarPanelV2
     - gui.pipeline_panel_v2 is an instance of PipelinePanelV2
     - gui.randomizer_panel_v2 is an instance of RandomizerPanelV2
     - gui.preview_panel_v2 is an instance of PreviewPanelV2
     - gui.status_bar_v2 is an instance of StatusBarV2
   - Optionally assert that these are placed in reasonable parents (left/right/center frames) without overspecifying geometry.

3. tests/gui_v2/test_gui_v2_pipeline_button_wiring.py
   - Continue to use a dummy PipelineController via monkeypatch, as in the existing harness.
   - Confirm that clicking the “Run Full Pipeline” button still results in exactly one call to the dummy controller’s start method, under the new layout.
   - If the button attribute or text changed due to the V2 layout, adjust the test to locate it reliably (id/attribute-based rather than fragile positional assumptions).

Step 5 – Headless/test-mode behavior
If tests fail due to GUI startup side effects (e.g., WebUI auto-launch), reuse the existing test-mode/Headless protection approach already present in the codebase (such as STABLENEW_GUI_TEST_MODE, STABLENEW_V2_GUI_TEST_MODE, or similar).

- Do NOT introduce new environment flags in this PR unless absolutely necessary.
- If a new flag is required, it must:
  - Default to “off” (no behavior change for normal users).
  - Only short-circuit unwanted side effects for tests (e.g., skip auto-launch).

8. Required Tests (Failing First)
Before making changes, Codex should run:
- pytest tests/gui_v2 -v
- pytest -v

and observe the current passing baseline of the V2 harness.

Then Codex should:
1. Implement the V2 panels and wiring as described.
2. Update or extend tests/gui_v2 as described.
3. Re-run:
   - pytest tests/gui_v2 -v
   - pytest -v

The first run after introducing the panels and test changes may fail due to missing attributes or layout differences; Codex must iterate until both commands succeed (with Tk/Tcl skips allowed).

9. Acceptance Criteria
This PR is complete when:
- New V2 panel modules exist under src/gui and define:
  - PipelinePanelV2
  - RandomizerPanelV2
  - PreviewPanelV2
  - SidebarPanelV2
  - StatusBarV2
- StableNewGUI in src/gui/main_window.py:
  - Instantiates and exposes these panels via stable attributes.
  - Continues to wire the primary Run button to the controller as before.
- tests/gui_v2:
  - Validates GUI startup.
  - Confirms the presence and types of V2 panels.
  - Confirms Run button -> controller wiring.
- pytest tests/gui_v2 -v passes (with acceptable Tk/Tcl skips).
- pytest -v completes without GUI-related import explosions and with GUI V2 tests included.
- No forbidden files were touched (controller/pipeline/api/utils/legacy tests).

10. Rollback Plan
If this PR needs to be rolled back:
- Delete the new V2 panel modules:
  - src/gui/pipeline_panel_v2.py
  - src/gui/randomizer_panel_v2.py
  - src/gui/preview_panel_v2.py
  - src/gui/sidebar_panel_v2.py
  - src/gui/status_bar_v2.py
- Revert changes in src/gui/main_window.py to its previous version (pre-PR-GUI-V2-MIGRATION-002).
- Revert changes to tests/gui_v2 and restore the previous harness behavior.
- Re-run:
  - pytest tests/gui_v2 -v
  - pytest -v
  to confirm that the test suite is back to the state achieved after PR-GUI-V2-MIGRATION-001.

11. Codex Execution Constraints
- Do not modify src/controller, src/pipeline, src/api, or src/utils.
- Do not modify tests/gui_v1_legacy/**.
- Keep main_window.py changes as small and mechanical as possible while still cleanly introducing the V2 panels.
- Do not add new business logic to the GUI; limit changes to layout/instantiation/wiring.
- Use clear, explicit attribute names (e.g., sidebar_panel_v2) to make tests simple and robust.
- Always post the full outputs of:
  - pytest tests/gui_v2 -v
  - pytest -v

12. Smoke Test Checklist
Before declaring success, Codex must verify:
- All five V2 panels are defined and importable.
- StableNewGUI exposes each panel as a public attribute.
- The V2 layout tests can locate and assert panel types without fragile widget traversal.
- The Run button wiring test passes under the new layout.
- The full pytest run completes without GUI import issues and shows the GUI V2 tests in the summary.
