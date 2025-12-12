Codex Execution Guide for PR-0: Pipeline Execution Hotfix
========================================================

Purpose
-------
This document tells Codex *exactly* how to apply PR-0 without hallucinating, drifting scope, or touching files outside the allowed set.

High-level Rules
----------------
1. **One PR = One Concern.**
   - Only fix the GUI → controller → pipeline execution path and lifecycle handling.
2. **Failing tests first.**
   - Write the new tests file, run it, confirm RED.
   - Only then implement the minimal code to go GREEN.
3. **No scope creep.**
   - Do not "cleanup" or "improve" unrelated code.
   - Do not touch files outside the Allowed Files list.
4. **Respect Architecture_v2.**
   - Controller owns lifecycle and CancelToken.
   - PipelineRunner is a separate concern.
   - GUI is UI-only and talks only to the controller.

Step-by-step for Codex
----------------------

Step 1 – Read the PR Template
- Open `PR-0_Pipeline_Execution_Hotfix.md`.
- Do not start coding until you understand:
  - Problem statement
  - Allowed/forbidden files
  - Required tests

Step 2 – Create the new tests file (RED)
- Create `tests/controller/test_app_controller_pipeline_flow_pr0.py`.
- Implement the four tests described in section 9 of the PR template:
  - `test_run_starts_pipeline_and_returns_to_idle`
  - `test_second_run_after_first_completes_succeeds`
  - `test_stop_sets_cancel_and_updates_lifecycle`
  - `test_pipeline_error_sets_error_state_and_recovers`
- Use a `FakePipelineRunner` defined inside the test module.
- Instantiate `AppController` with `threaded=False` so runs are synchronous.
- Use Tk root and `MainWindow` from `src.gui.main_window_v2` (hide the window via `.withdraw()` to avoid UI popups).

Step 3 – Run the new tests (expect RED)
- Run:
  - `pytest tests/controller/test_app_controller_pipeline_flow_pr0.py -v`
- Capture and show the failing output.
- Do NOT modify any non-test code yet.

Step 4 – Implement PipelineRunner module
- Create `src/controller/pipeline_runner.py`.
- Define:
  - `class PipelineRunner(Protocol):` with `.run(config, cancel_token, log_fn)`.
  - `class DummyPipelineRunner(PipelineRunner):` with stubbed behavior (log a few entries, respect cancel_token, then return).
  - `class RealPipelineRunner(PipelineRunner):` that will eventually bridge to the real pipeline. In PR-0 this may be minimal but must:
    - Log that it has started and ended.
    - Catch exceptions and re-raise them or let the controller handle them.
- Do not try to redesign the pipeline or replace existing Pipeline classes; just call them if needed.

Step 5 – Wire AppController to PipelineRunner
- Open `src/controller/app_controller.py`.
- Import `PipelineRunner` and `DummyPipelineRunner` from `src.controller.pipeline_runner`.
- Ensure `AppController.__init__` signature includes `pipeline_runner: Optional[PipelineRunner] = None` and `threaded: bool = True`.
- Inside `__init__`, assign:
  - `self.pipeline_runner = pipeline_runner or DummyPipelineRunner()`
- Confirm that `_run_pipeline_thread` calls `self.pipeline_runner.run(config, cancel_token, log_fn)` exactly once per run.
- Ensure `_set_lifecycle_threadsafe` and `_append_log_threadsafe` behave correctly when `threaded=False` (direct calls rather than `after`).

Step 6 – Fix lifecycle transitions and stop behavior
- In `on_run_clicked`:
  - If lifecycle is RUNNING:
    - Log and return (no second pipeline started).
  - Otherwise:
    - Create a new `CancelToken`.
    - Set lifecycle to RUNNING.
    - Start worker (thread or sync depending on `threaded`).
- In `_run_pipeline_thread`:
  - Try:
    - Log start.
    - Call `pipeline_runner.run(...)`.
    - Log completion or cancellation.
  - Except Exception:
    - Log error (using `_append_log_threadsafe`).
    - Set lifecycle to ERROR with `last_error` message.
  - Finally:
    - Ensure lifecycle is set back to IDLE (either directly or after ERROR).
- In `on_stop_clicked`:
  - If not RUNNING, log and return.
  - Set lifecycle to STOPPING.
  - Call `cancel_token.cancel()`.
  - In synchronous (`threaded=False`) mode, you may set lifecycle back to IDLE directly after triggering cancel.

Step 7 – Ensure GUI wiring is minimal and correct
- Open `src/gui/main_window_v2.py`.
- Confirm that:
  - `run_button.command = controller.on_run_clicked`
  - `stop_button.command = controller.on_stop_clicked`
  - `preview_button.command = controller.on_preview_clicked`
- Confirm `bottom_zone.status_label` and `bottom_zone.log_text` are what AppController expects.
- Do **not** add new widgets, change layout, or restyle anything in this PR.

Step 8 – (Optional) main.py wiring
- Only if necessary to make the v2 controller path the active one in your environment:
  - Update `src/main.py` to construct `MainWindow`, `AppController`, and start the Tk mainloop using this pairing.
- Keep this wiring tiny and focused.

Step 9 – Run tests again (expect GREEN)
- Run:
  - `pytest tests/controller/test_app_controller_pipeline_flow_pr0.py -v`
  - `pytest tests/controller/test_app_controller.py -v` (if it exists)
- Show full output.
- Only if all tests pass should you consider this PR complete.

What Codex MUST NOT Do
----------------------
- Do not modify:
  - `src/pipeline/*`
  - `src/api/*`
  - Any GUI files other than `src/gui/main_window_v2.py`
  - Any tests outside `tests/controller/`
- Do not:
  - Rename existing public classes or functions.
  - Change function signatures outside the controller/pipeline runner boundary.
  - Introduce new dependencies.
  - "Refactor" unrelated parts of the codebase.
- If something seems to require broader changes, STOP and request a new PR design.

Completion Checklist for Codex
------------------------------
You are done when:
- All new tests in `test_app_controller_pipeline_flow_pr0.py` pass.
- Existing controller tests pass.
- No forbidden files were touched.
- Pressing Run in the GUI (via the v2 path) produces clear log output and does not freeze the UI.
