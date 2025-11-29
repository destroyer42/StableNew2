PR ID: PR-GUI-V2-MIGRATION-001
Title: Archive Legacy GUI Tests and Establish GUI V2 Test Harness

1. Summary
This PR formally retires the legacy GUI v1 test suite and introduces a focused GUI v2 test harness aligned with the Architecture_v2 plan. It moves the old tests into a clearly marked legacy folder (excluded from normal CI), adds a minimal but intentional v2 GUI test suite, and updates pytest configuration so new development and refactors are guided by the v2 architecture instead of the historic GUI.

2. Problem Statement
The current tests/gui suite encodes legacy GUI v1 behavior (old layout, old ConfigPanel API, old metadata model). The refactor has already diverged from that architecture (new center notebook, v2 ConfigPanel semantics, SAFE/RAND/THEME work), which makes the old GUI tests both:
- Misaligned with the product vision, and
- Expensive to keep green, requiring extensive shims and backwards-compatibility layers.

Continuing to repair and maintain these tests would force the v2 GUI to mimic obsolete UX decisions, slow down refactors, and inflate complexity. We need to flip the default testing stance from “preserve v1 at all costs” to “treat v2 as the source of truth.”

3. Goals
- Archive the legacy GUI test suite so it no longer drives design or breaks CI.
- Introduce a new, small, focused GUI v2 test harness aligned with Architecture_v2.
- Ensure pytest’s default configuration runs the v2 GUI tests and ignores legacy tests by default.
- Keep changes tightly scoped to test layout, configuration, and minimal environment flags (no GUI behavior changes in this PR).
- Prepare the ground for future v2 GUI feature work and pipeline/UX improvements without legacy drag.

4. Non-goals
- No functional changes to src/gui/main_window.py or other GUI behavior (beyond very small adaptations strictly needed for test harness bootstrapping, if any).
- No changes to controller, pipeline, api, or utils layers.
- No attempt to partially “port” legacy GUI v1 tests into v2; all such work will happen in future, targeted PRs if needed.
- No large redesign of how pytest is integrated with the project; we only tune testpaths and markers where necessary.

5. Allowed Files
Codex may modify or create only the following paths in this PR:
- tests/gui_v1_legacy/** (new folder, full copy/move of existing legacy tests)
- tests/gui_v2/** (new folder, new v2-focused tests)
- pyproject.toml (pytest configuration only)
- docs/pr_templates/PR-GUI-V2-MIGRATION-001_Archive_Legacy_GUI_Tests_And_Introduce_GUI_V2_Harness.md (this PR doc if checked in)
- docs/pr_templates/Codex_Run_Sheet_PR-GUI-V2-MIGRATION-001.md (optional, if we decide to commit the run sheet)

If absolutely necessary for basic v2 GUI test startup, Codex may add a single, minimal environment toggle or helper in:
- src/gui/main_window.py
But only under explicit, narrowly defined instructions (see Step-by-step Implementation).

6. Forbidden Files
Codex must not modify:
- Any files under src/controller/**
- Any files under src/pipeline/**
- Any files under src/api/**
- src/utils/** (including randomizer, preferences, config manager, etc.)
- Any docs outside docs/pr_templates related to this PR
- Any tools scripts, CI pipeline definitions, or configuration beyond the pytest section of pyproject.toml

Any need to touch those areas must be deferred to a future PR.

7. Step-by-step Implementation

Step 1 – Archive legacy GUI tests
1. Create a new folder:
   - tests/gui_v1_legacy
2. Move all existing GUI test modules from:
   - tests/gui/
   into:
   - tests/gui_v1_legacy/
3. Preserve relative filenames and internal imports as-is (do not edit imports in this PR). The intent is archival, not functional restoration.
4. Optional but recommended: add a short module-level docstring in tests/gui_v1_legacy/__init__.py (or a README.md in that folder) explaining that this tree is frozen and not part of the v2 CI path.

Step 2 – Introduce GUI v2 test folder and skeleton tests
1. Create a new folder:
   - tests/gui_v2
2. Add minimal skeleton tests that reflect our current v2 direction without over-specifying behavior. Examples (names may be adjusted to match repo idioms):
   - tests/gui_v2/test_gui_v2_startup.py
     - Verifies that StableNewGUI (or the intended v2 entrypoint) can be imported and constructed in a test environment without raising exceptions when Tk/Tcl is available.
     - Skips gracefully if Tk/Tcl is not available, similar to existing patterns in test_api_status_panel.
   - tests/gui_v2/test_gui_v2_layout_skeleton.py
     - Asserts only high-level layout facts that are stable under v2:
       - A central notebook/panel exists (e.g., center_notebook attribute on StableNewGUI).
       - The primary panes/frames are wired in a consistent way (high-level, not pixel-perfect).
   - tests/gui_v2/test_gui_v2_pipeline_button_wiring.py
     - Uses monkeypatch to inject a dummy PipelineController and confirms that pressing the primary “Run” button (or equivalent) triggers the controller’s start method exactly once, without starting real work.
3. All v2 GUI tests must:
   - Avoid hitting real WebUI discovery or network calls.
   - Avoid triggering real pipelines.
   - Use monkeypatching where necessary to stub out expensive or non-deterministic operations.
4. All v2 tests should be small, fast, and designed specifically for Architecture_v2. They must not depend on legacy ConfigPanel v1 behavior.

Step 3 – Pytest configuration: prefer v2
1. Update pyproject.toml’s pytest configuration (e.g., [tool.pytest.ini_options]) so that:
   - tests/gui_v2 is included in testpaths by default.
   - tests/gui (if it still exists) is no longer in testpaths, and tests/gui_v1_legacy is not referenced by default.
2. Ensure that safety, utils, pipeline, and controller tests remain in the default testpaths.
3. Do not change markers or add global options beyond what is strictly necessary to make the new GUI v2 test suite run in a typical dev environment.

Step 4 – Optional: Introduce a v2 GUI test mode flag
This step is optional and should be done only if importing/constructing the GUI in tests requires extra isolation.

1. If needed, add a minimal, non-invasive environment check in src/gui/main_window.py, for example:
   - When an environment variable like STABLENEW_V2_GUI_TEST_MODE=1 is set, the GUI:
     - Skips webui auto-launch.
     - Skips any long-running discovery tasks.
     - Avoids side effects that are incompatible with headless test environments.
2. This flag must:
   - Default to “off” (normal behavior when not set).
   - Be checked only near startup/initialization code.
   - Not change runtime behavior for real users when the flag is not present.
3. Any changes to main_window.py must be as small as possible and only in support of making v2 tests pass reliably in headless or partially headless environments.

Step 5 – Clean up direct references to tests/gui in tooling (if any)
1. If pyproject.toml or any helper scripts currently reference tests/gui explicitly, update them to point to tests/gui_v2 instead.
2. Do not add any new scripts or tools in this PR; just adjust existing references if they break due to the folder move.

8. Required Tests (Failing First)
Before implementing changes, Codex should:
1. Run:
   - pytest tests/gui -v
   to confirm that this currently fails with multiple legacy GUI v1 assumptions.
2. After moving tests to tests/gui_v1_legacy and adding tests/gui_v2 skeletons, run:
   - pytest tests/gui_v2 -v
   and confirm that the new tests fail or error until the minimal harness is wired.
3. Then implement the minimal code and test updates described above until:
   - pytest tests/gui_v2 -v passes cleanly.
4. Finally, run the default suite:
   - pytest -v
   and confirm that:
   - The legacy GUI v1 tests are no longer part of the default run.
   - The rest of the project (safety, utils, controller, pipeline) remains green or in its pre-existing state.

9. Acceptance Criteria
This PR is considered complete when:
- All legacy GUI tests have been moved from tests/gui/ to tests/gui_v1_legacy/.
- tests/gui_v2/ exists and contains a small, focused set of v2-aligned GUI tests.
- pytest’s default configuration runs tests/gui_v2 but not tests/gui or tests/gui_v1_legacy.
- pytest tests/gui_v2 -v passes in a typical dev environment (modulo Tk/Tcl skips).
- pytest -v runs without import-time GUI explosions and reflects the new testpaths.
- No changes have been made to src/controller, src/pipeline, src/api, or src/utils in this PR.

10. Rollback Plan
If this PR needs to be rolled back:
- Move tests/gui_v1_legacy/* back to tests/gui/.
- Remove or delete tests/gui_v2/.
- Restore the previous pytest configuration in pyproject.toml (testpaths and any other adjustments).
- Remove any environment toggles added for GUI test mode, if they cause confusion in the reverted state.

Because this PR does not delete logic or change core src behavior (beyond an optional minor test-mode guard), rollback is low-risk and mainly affects test configuration.

11. Codex Execution Constraints
- Do not modify src/controller, src/pipeline, src/api, or src/utils in this PR.
- Keep changes to src/gui/main_window.py (if any) minimal and strictly in support of headless-safe v2 GUI tests.
- Do not attempt to “fix” legacy tests in tests/gui_v1_legacy; they are archived and may be broken.
- Do not introduce any new GUI features or behavior changes; focus strictly on test harness and configuration.
- Always run tests in the following order and paste outputs back to the human:
  1) pytest tests/gui_v2 -v
  2) pytest -v

12. Smoke Test Checklist
Before declaring success, Codex must verify:
- Folder structure:
  - tests/gui_v1_legacy exists and contains the old GUI tests.
  - tests/gui_v2 exists and contains the new v2 tests.
- Pytest configuration:
  - pyproject.toml testpaths include tests/gui_v2 but not tests/gui or tests/gui_v1_legacy.
- Test runs:
  - pytest tests/gui_v2 -v passes (with reasonable Tk/Tcl skips as appropriate).
  - pytest -v completes without legacy GUI v1 import errors and shows the new GUI v2 tests in its output.

Once all of the above are confirmed, PR-GUI-V2-MIGRATION-001 can be considered ready for review.
