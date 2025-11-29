Codex Execution Guide for PR-0.1: Runtime Entry Alignment
========================================================

Purpose
-------
This guide tells you exactly how to implement PR-0.1 so that:

- The StableNew runtime entry (`src/main.py`) uses the **v2 GUI + AppController** stack.
- You keep the change small, surgical, and within scope.
- You avoid touching pipeline internals or unrelated modules.

High-level Rules
----------------
1. **Scope is tiny.** Only `src/main.py` is intended to change.
2. **Do not change pipeline internals.** No edits in `src/pipeline/*` or `src/api/*`.
3. **No GUI redesign.** Do not alter layouts or widgets; only change which GUI/controller is constructed in the entrypoint.
4. **Preserve logging and single-instance behavior.** Anything related to `STABLENEW_LOGGING_BYPASS` and `_INSTANCE_PORT` should remain intact.

Step-by-step Instructions
-------------------------

Step 1 – Read the PR spec
- Open and read `PR-0.1_Runtime_Entry_Alignment.md` fully.
- Summarize (to yourself) the key requirements:
  - `src/main.py` must create:
    - Tk root
    - `MainWindow_v2`
    - `AppController`
  - Legacy `StableNewGUI` entrypoint should no longer be the default path.

Step 2 – Inspect current `src/main.py`
- Examine imports and the `main()` function.
- Identify:
  - Where logging bypass is configured (env var check).
  - Where single-instance locking is done.
  - Where `StableNewGUI` (or any other GUI) is created and run.
- Do **not** remove these concerns. You will only swap the GUI construction at the end.

Step 3 – Update imports to use v2
- Remove or stop using the legacy GUI import:

  - `from .gui.main_window import StableNewGUI`

- Add imports for the v2 stack (using correct package-relative imports as in the repo):

  - `import tkinter as tk`
  - `from .gui.main_window_v2 import MainWindow`
  - `from .controller.app_controller import AppController`

- If necessary, import `DummyPipelineRunner` from `src.controller.pipeline_runner`, but only if the current `AppController` does not already default to an appropriate runner.

Step 4 – Replace legacy GUI construction with v2 wiring
- Locate the code in `main()` where the legacy GUI is instantiated, e.g.:

  - `app = StableNewGUI()`
  - `app.run()`

- Replace it with the v2 sequence:

  - `root = tk.Tk()`
  - `window = MainWindow(root)`
  - `controller = AppController(window, threaded=True)`
    - Optionally pass a pipeline runner if needed, but keep it simple and aligned with PR-0 tests.
  - `root.mainloop()`

- Ensure these lines are executed only after the single-instance lock has been successfully acquired.

Step 5 – Keep logging and single-instance behavior intact
- Confirm that:

  - The early logging bypass logic remains unchanged.
  - The `_acquire_single_instance_lock()` logic and call site remain the same.
  - On failure to acquire the lock, the function still shows a messagebox / prints a message and returns without creating any GUI.

- Do not change user-visible strings related to the “already running” message as part of this PR.

Step 6 – Run tests
- Run at least:

  - `pytest tests/controller/test_app_controller_pipeline_flow_pr0.py -v`

- Show the full output.
- Confirm that all tests are still green.
- Do not add new tests in this PR unless requested.

Step 7 – Manual smoke test (human task)
- After you’ve made the code changes and tests are green, inform the human to:

  - Run `python -m src.main`.
  - Verify that the GUI they see matches `main_window_v2`.
  - Press Run once and then twice to confirm no hang.

What You Must NOT Do
--------------------
- Do not modify:
  - `src/pipeline/*`
  - `src/api/*`
  - Any GUI files except possibly `src/gui/main_window_v2.py` (and only after explicit human approval).
- Do not:
  - Change logging formats, loggers, or handlers.
  - Change the instance lock port or semantics.
  - Introduce new dependencies or modules.
  - “Refactor” unrelated code in `src/main.py`.

Completion Checklist
--------------------
You are done when:

- `src/main.py` uses the v2 GUI/controller stack as described.
- Controller tests added in PR-0 are still passing.
- The human’s manual smoke test confirms:
  - v2 GUI appears when running `python -m src.main`.
  - Run can be pressed twice without hang.
  - Single-instance behavior still works.
