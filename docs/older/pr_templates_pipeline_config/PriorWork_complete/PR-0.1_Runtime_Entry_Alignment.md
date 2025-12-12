PR-0.1: Runtime Entry Alignment (Switch GUI Entry to v2 Controller Path)
======================================================================

1. Title
--------
Align StableNew runtime entrypoint to the Architecture_v2 GUI/controller path (PR-0.1: Runtime Entry Alignment).

2. Summary
----------
PR-0.0 (Pipeline Execution Hotfix) stabilized the **controller + Fake/Dummy runner** path and added tests to prove that `AppController` and `MainWindow_v2` handle run/stop, lifecycle, and error flows correctly.

However, the live GUI that launches when running `python -m src.main` was still using the **legacy GUI stack** (e.g., `StableNewGUI` from `src/gui/main_window.py`) in the last known snapshot, and likely remained partially wired that way in later iterations. As a result:

- PR-0’s fixes and tests exercised a **different path** than the one the user actually clicks in the real app.
- The “Run Pipeline” button in the live GUI continues to hang because it’s still using the old controller/pipeline wiring.

PR-0.1 solves this by **aligning the runtime entrypoint (`src/main.py`) with the tested v2 architecture path**:

- `src/main.py` will create:
  - a Tk root
  - a `MainWindow` from `src.gui.main_window_v2`
  - an `AppController` from `src.controller.app_controller`
- The logging bypass and single-instance-lock behavior are preserved.
- The v1 GUI entrypoint is retired for normal execution (it can be left in place only as a dead convenience script if needed, but `main.py` must use v2).

This PR is a small but critical bridge: it makes the **tested** controller path the **actual** runtime path.

3. Problem Statement
--------------------
From the StableNew-MoreSafe snapshot and subsequent behavior:

- `src/main.py` still imports and launches `StableNewGUI` from `src.gui.main_window`:
  - `from .gui.main_window import StableNewGUI`
  - `app = StableNewGUI(); app.run()`
- The v2 GUI/controller path (`MainWindow_v2`, `AppController`) exists in the repo and has dedicated tests (PR-0), but `src/main.py` doesn’t use it.
- As a result:
  - Tests verify the behavior of `AppController + MainWindow_v2`.
  - The real GUI the user interacts with may still be using legacy wiring, causing pipeline hangs even after PR-0.

We need the **single source of truth** for GUI runtime to be the v2 stack so that:

- When tests are green, the real app behaves accordingly.
- Future PRs that target the v2 path actually affect what the user sees.

4. Goals
--------
- Make `src/main.py` launch the v2 GUI/controller stack:
  - Tk root → `MainWindow_v2` → `AppController` (with threaded worker).
- Preserve existing process-level behavior:
  - Logging bypass via `STABLENEW_LOGGING_BYPASS` env var.
  - Single-instance lock via `_INSTANCE_PORT` and `_acquire_single_instance_lock()`.
  - Friendly error messaging if another instance is already running.
- Keep the integration minimal and focused: no new UI widgets, no config changes, no pipeline refactors.

5. Non-goals
------------
- No redesign of the GUI (layout, widgets, theming).
- No changes to controller internals beyond what PR-0 already made.
- No changes to pipeline implementation in `src/pipeline/*`.
- No new configuration schema, logging schema, or manifest behavior.
- No feature additions: this is wiring-only.

6. Allowed Files
----------------
Only the following may be modified in this PR:

- `src/main.py`

Optionally (only if absolutely required to correct imports or wiring, and even then minimally):

- `src/gui/main_window_v2.py`

7. Forbidden Files
------------------
These must **not** be modified in PR-0.1:

- Any files under `src/pipeline/`
- Any files under `src/api/`
- Any files under `src/gui/` other than `src/gui/main_window_v2.py` (and that only if truly necessary)
- Any controller modules besides `src/controller/app_controller.py` (which should already be correct from PR-0; do not modify it in this PR)
- Any tests (PR-0 already covered controller behavior; this PR is wiring-only)
- CI configs, pyproject.toml, linting configs, or GitHub workflows

If a change to any forbidden file feels necessary, STOP and request a new PR design rather than expanding PR-0.1 scope.

8. Step-by-step Implementation Plan
-----------------------------------

### Step 1 – Inspect current `src/main.py`
- Confirm that it still resembles the legacy entrypoint, roughly:

  - Imports:
    - `from .gui.main_window import StableNewGUI`
    - `from .utils import setup_logging`
  - Behavior:
    - Applies optional logging bypass (`STABLENEW_LOGGING_BYPASS`).
    - Sets up single-instance TCP lock on `_INSTANCE_PORT`.
    - On success, constructs `StableNewGUI()` and calls `app.run()`.
    - On failure, shows a messagebox / prints an error about an existing instance.

- Do **not** remove or break:
  - Logging bypass
  - Single-instance lock
  - Error message behavior

These concerns must remain intact after PR-0.1.

### Step 2 – Import the v2 GUI/controller stack
Modify imports at the top of `src/main.py`:

- Remove or stop using the legacy GUI class import:
  - `from .gui.main_window import StableNewGUI`
- Add imports for the v2 stack (names may need to be aligned to actual code, but conceptually):

  - `import tkinter as tk`
  - `from .gui.main_window_v2 import MainWindow`
  - `from .controller.app_controller import AppController`

- If `PipelineRunner` / `DummyPipelineRunner` is needed explicitly, import it from:
  - `from .controller.pipeline_runner import DummyPipelineRunner`
  or rely on `AppController`’s default runner if appropriate.

> IMPORTANT: Do not introduce circular imports; keep imports minimal and in line with existing module structure.

### Step 3 – Replace legacy GUI construction with v2 wiring
In the `main()` function (or equivalent runtime entry function), after the single-instance lock is acquired:

- **Before (legacy):**

  - `app = StableNewGUI()`  
  - `app.run()`

- **After (v2):**

  - Create a Tk root:
    - `root = tk.Tk()`
  - Construct the v2 main window:
    - `window = MainWindow(root)`
  - Construct the v2 controller:
    - `controller = AppController(window, threaded=True)`
      - Optionally pass a `pipeline_runner` if you want to explicitly select `DummyPipelineRunner` vs a real runner; otherwise let `AppController`’s default apply.
  - Start the Tk mainloop:
    - `root.mainloop()`

Keep the existing locking behavior around this block unchanged; only swap out the GUI stack.

### Step 4 – Preserve single-instance and logging bypass behavior
Ensure that:

- The logging bypass at the top of `src/main.py` is untouched.
- `_acquire_single_instance_lock()` remains unchanged and is called exactly once in `main()` before creating the GUI.
- The “StableNew is already running” error still uses `messagebox.showerror` if available, or `stderr` fallback if Tk isn’t ready.

### Step 5 – Optional: Environment toggle for v1 vs v2 (only if truly needed)
If, and only if, you need a temporary escape hatch to compare v1 vs v2, you may:

- Add an env-var-based switch, e.g., `STABLENEW_USE_V1_GUI`.
- Default behavior should be v2 (Architecture_v2 alignment is the goal).

Suggested pattern:

- If `os.getenv("STABLENEW_USE_V1_GUI") == "1"`:
  - Import and create `StableNewGUI` as before.
- Else:
  - Use the v2 path described in Step 3.

If you add such a switch, document it in a comment and keep it lightweight. It should be easy to remove in a later PR once v2 is fully validated.

### Step 6 – Manual smoke test
Because this PR is pure wiring, and PR-0 already provides controller tests, this PR can rely on **manual smoke tests** rather than new automated tests:

1. Run `python -m src.main` to launch StableNew.
2. Confirm:
   - The window that opens is the v2 layout (as defined by `main_window_v2`), not the old v1 GUI.
3. Press “Run”:
   - Confirm that the log panel shows controller messages from `AppController`.
   - Confirm that the status bar changes from `Idle` → `Running` → `Idle` when using the dummy/stub runner.
4. Press “Run” a second time:
   - Confirm that the app does not hang and logs indicate another full run.
5. Optionally, trigger STOP (if wired to CancelToken via PR-0):
   - Confirm that `Stop` transitions from `RUNNING` to `STOPPING` and back to `IDLE`.

9. Required Tests
-----------------
PR-0.1 is a wiring-only adjustment, and PR-0 already introduced tests that verify the behavior of `AppController` and the v2 GUI/controller flow. For this PR:

- **No new tests are strictly required**, provided that:
  - PR-0 tests continue to pass (`tests/controller/test_app_controller_pipeline_flow_pr0.py`).
  - Manual smoke tests validate that `src/main.py` now launches the same path those tests exercise.

If desired, a later PR may introduce a small, isolated test that asserts the main entrypoint imports and constructs `MainWindow_v2` and `AppController`, but that is beyond the scope of PR-0.1.

10. Acceptance Criteria
-----------------------
PR-0.1 is accepted when:

- Running `python -m src.main` launches the v2 GUI created by `MainWindow_v2`.
- Pressing Run in the GUI:
  - Produces log output from `AppController` (e.g., messages that clearly originate from the v2 controller path).
  - Changes lifecycle and status as expected (Idle → Running → Idle) when using the dummy/stub runner.
- Pressing Run a second time does not hang or crash the GUI.
- The single-instance locking and logging bypass behaviors are unchanged and still work as previously.
- No forbidden files are modified.

11. Rollback Plan
-----------------
To revert PR-0.1:

- Restore the prior version of `src/main.py` from git history (the version that used `StableNewGUI`).
- No data migrations or schema changes are involved; rollback is purely code-level.

12. Codex Execution Constraints
-------------------------------
For Codex (or any implementer):

- Only touch `src/main.py` (and only touch `src/gui/main_window_v2.py` if absolutely necessary and after confirming scope with the human).
- Do not modify any pipeline, API, controller, or GUI files outside the allowed set.
- Do not rename or remove `main()` or change its external behavior (calling `main()` should still start the app, but now via v2).
- Do not “clean up” or refactor unrelated code in `src/main.py`; keep the diff narrow and aligned with the PR steps.

13. Smoke Test Checklist
------------------------
After implementation, the implementer or human should:

1. Run `pytest tests/controller/test_app_controller_pipeline_flow_pr0.py -v` to ensure controller tests are still green.
2. Run `python -m src.main` and:
   - Verify the v2 GUI appears.
   - Click Run and ensure logs and status behave as expected.
   - Click Run again to confirm no hang.
3. Optionally, verify that attempting to start a second instance of StableNew still produces the “already running” error from the single-instance lock.
