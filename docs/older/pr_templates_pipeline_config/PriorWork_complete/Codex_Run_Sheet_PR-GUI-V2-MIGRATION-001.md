Codex Run Sheet: PR-GUI-V2-MIGRATION-001
Title: Archive Legacy GUI Tests and Introduce GUI V2 Harness

You are implementing PR-GUI-V2-MIGRATION-001. Follow these steps exactly and do not go out of scope.

1. Scope Guardrails
- You MAY modify or create:
  - tests/gui_v1_legacy/**
  - tests/gui_v2/**
  - pyproject.toml (pytest configuration only)
- You MAY (optionally) make a minimal, test-mode-only change to src/gui/main_window.py if absolutely required to make GUI v2 tests pass in headless mode.
- You MUST NOT touch:
  - src/controller/**
  - src/pipeline/**
  - src/api/**
  - src/utils/**
  - Any docs outside docs/pr_templates for this PR

2. Current-State Baseline (informational)
- The existing tests/gui suite targets the legacy GUI v1 architecture and is failing due to mismatched ConfigPanel APIs and v2 refactor changes.
- Your job is NOT to fix those tests.
- Your job IS to:
  - Archive them under tests/gui_v1_legacy, and
  - Stand up a minimal v2-aligned GUI test harness in tests/gui_v2.

3. Step-by-step Implementation

Step A – Archive legacy GUI tests
1) Create folder tests/gui_v1_legacy if it does not exist.
2) Move all files currently under tests/gui/ into tests/gui_v1_legacy/.
   - Preserve their filenames and package structure.
   - Do NOT modify their contents in this PR.
3) Ensure tests/gui/ is empty (or removed) once the move is complete.

Step B – Create GUI v2 test folder and skeleton tests
1) Create tests/gui_v2 if it does not exist.
2) Add the following minimal test modules (names may be slightly adjusted to match repo conventions):
   - tests/gui_v2/test_gui_v2_startup.py
     - Imports the intended v2 GUI entrypoint (likely StableNewGUI from src.gui.main_window).
     - Tries to construct the GUI in a Tk environment.
     - Skips cleanly if Tk/Tcl is not available (pattern similar to tests/gui/test_api_status_panel.py).
   - tests/gui_v2/test_gui_v2_layout_skeleton.py
     - Constructs the v2 GUI (subject to Tk availability).
     - Asserts a small number of high-level invariants only, e.g.:
       - gui.center_notebook exists (or the appropriate v2 attribute name).
       - Primary layout frames/panes exist and use expected type(s).
   - tests/gui_v2/test_gui_v2_pipeline_button_wiring.py
     - Uses monkeypatch to:
       - Replace PipelineController with a dummy recording object.
       - Prevent webui auto-launch and messagebox dialogs.
     - Constructs the GUI and simulates clicking the primary “Run” button.
     - Asserts that the dummy controller’s start method (or equivalent) was called exactly once.
3) All v2 tests must be small and self-contained and must skip gracefully in environments without Tk/Tcl.

Step C – Update pytest configuration
1) Open pyproject.toml and locate the pytest configuration section (tool.pytest.ini_options).
2) Ensure testpaths includes:
   - tests/gui_v2
   - the rest of the standard test areas (tests/utils, tests/controller, tests/pipeline, tests/safety, etc.)
3) Ensure testpaths does NOT include:
   - tests/gui
   - tests/gui_v1_legacy
4) Do not add new markers or command-line options; only adjust testpaths (and, if necessary, a minimal addopts tweak).

Step D – Optional test-mode guard in src/gui/main_window.py
Only do this if tests fail due to:
- WebUI auto-booting
- Long-running discovery logic
- Headless Tk issues that require the code to skip certain startup behaviors.

If and only if needed:
1) Add a small environment check near the top-level GUI startup code in src/gui/main_window.py. Example pattern:
   - If os.environ.get("STABLENEW_V2_GUI_TEST_MODE") == "1":
     - Disable WebUI auto-launch.
     - Disable long-running discovery or loops.
2) Do NOT change behavior when STABLENEW_V2_GUI_TEST_MODE is NOT set.
3) Keep this block as small and localized as possible.

4. Test Execution Order
Run tests in this order and include the full output in your report:

1) pytest tests/gui_v2 -v
   - Expect these to fail or error at first while you are wiring the harness.
   - After fixes, this must pass (with Tk-related skips allowed).

2) pytest -v
   - Confirm that:
     - GUI v2 tests are included.
     - There are no import errors from legacy GUI v1 tests.
     - Non-GUI suites (safety, utils, pipeline, controller) remain in their previous state.

5. Success Criteria
You are done when:
- tests/gui_v1_legacy contains all the old GUI tests, and tests/gui is no longer used.
- tests/gui_v2 exists and contains a small, focused v2-aligned test suite as described above.
- pyproject.toml’s pytest configuration runs tests/gui_v2 but not tests/gui or tests/gui_v1_legacy by default.
- pytest tests/gui_v2 -v passes (modulo Tk/Tcl skips).
- pytest -v completes without legacy GUI v1 import explosions.

Do NOT expand the scope of this PR beyond what is listed here.
