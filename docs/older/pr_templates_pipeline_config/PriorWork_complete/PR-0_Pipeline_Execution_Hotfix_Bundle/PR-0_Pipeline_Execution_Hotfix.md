PR-0: Pipeline Execution Hotfix (GUI Run-Button Hang Fix)
========================================================

1. Title
--------
Restore Stable Pipeline Execution from GUI (PR-0: Pipeline Execution Hotfix)

2. Summary
----------
This PR restores a *stable, predictable, debuggable* pipeline execution path from the GUI, eliminating the "Run Pipeline" hang and thread crashes that have accumulated during recent refactors.

It does this by:
- Repairing the controller → pipeline API mismatch.
- Ensuring a valid StructuredLogger is used (or intentionally bypassed) in all pipeline entrypoints.
- Guaranteeing lifecycle transitions (IDLE → RUNNING → IDLE / ERROR) are consistent and test-covered.
- Adding focused tests that simulate real GUI-driven runs and a second run after the first completes.

This PR **does not introduce any new features.** It is a stability / correctness hotfix and the foundation for all future Architecture_v2 PRs.

3. Problem Statement
--------------------
Symptoms currently observed (from logs and history summary):

- Pressing **Run Pipeline** in the GUI can cause:
  - Immediate hang / unresponsive UI.
  - Background `AttributeError` exceptions such as `'list' object has no attribute 'active'`.
  - Failures due to mismatched controller methods (`start_pipeline` vs `run_pipeline` / `run_full_pipeline`).

- The **controller → pipeline** integration is in a partially upgraded state:
  - Older GUI branches expect `PipelineController.start_pipeline(...)`.
  - Newer pipeline code paths expose different methods (`run_pipeline`, `run_full_pipeline`, executor-based stages).
  - StructuredLogger wiring was removed/renamed in some places but still assumed in others.

- The result is that GUI runs can:
  - Crash the worker thread.
  - Leave lifecycle stuck in RUNNING.
  - Emit no clear error to the user while silently failing in logs.

This PR is intended as the **single, authoritative** hotfix to get back to a known good baseline so that further Architecture_v2 work is safe.

4. Goals
--------
- Re-establish a **single, stable entrypoint** from GUI → controller → pipeline.
- Ensure pipeline runs initiated from the GUI:
  - Start reliably.
  - Either finish successfully or fail with a surfaced error.
  - Return lifecycle to IDLE (or ERROR then IDLE) in all cases.
- Ensure a **second run** after a completed run does not hang, crash, or silently fail.
- Ensure tests cover:
  - Lifecycle transitions.
  - Basic controller/pipeline wiring.
  - Error-path handling (exceptions in pipeline background thread).

5. Non-goals
------------
- No new GUI features or layout changes.
- No changes to randomizer/matrix logic.
- No restructure of the pipeline internals (Executor, stages, etc.).
- No new config schema or manifest schema changes.
- No performance tuning in this PR (that belongs in later pipeline-focused PRs).

6. Allowed Files
----------------
Only the following files may be modified or created in this PR:

**Existing (may be edited):**
- `src/controller/app_controller.py`
- `src/gui/main_window_v2.py` (only to ensure correct controller wiring, no layout redesign)
- `src/main.py` (only if needed to ensure the new controller-based entrypoint is used predictably)

**New (to be created by this PR):**
- `src/controller/pipeline_runner.py`
- `tests/controller/test_app_controller_pipeline_flow_pr0.py`

7. Forbidden Files
------------------
The following files must **not** be modified in this PR:
- Any modules under `src/pipeline/` (implementation details stay as-is).
- Any modules under `src/api/`.
- Any modules under `src/gui/` *except* `main_window_v2.py` as noted above.
- Any test files outside `tests/controller/`.
- Project metadata, CI, linting configs, or packaging configs.

If a change seems necessary in a forbidden file, STOP and request a new PR design instead of modifying it in PR-0.

8. Step-by-step Implementation Plan
-----------------------------------

**Step 1 – Introduce a dedicated PipelineRunner abstraction**
- Create `src/controller/pipeline_runner.py`.
- Define a `PipelineRunner` Protocol (or ABC) that matches:

  - `run(config: RunConfig, cancel_token: CancelToken, log_fn: Callable[[str], None]) -> None`

- Move / mirror the existing Protocol definition out of `app_controller.py` into this new module **or** import it explicitly if already defined there, to keep controller lean.
- Provide two implementations:
  - `DummyPipelineRunner` – maintains existing stub behavior (short sleep, logs a few messages, respects CancelToken).
  - `RealPipelineRunner` – a thin adapter that calls the existing pipeline entrypoint (e.g., `Pipeline.run_full_pipeline`), but in PR-0 this can be **minimal**:
    - It can log that it is not yet fully wired for prompts/randomizer if necessary.
    - It must still catch exceptions and re-raise or log appropriately so the controller error path is exercised.

> NOTE: The goal for PR-0 is correctness and lifecycle stability, not full feature parity. It is acceptable for `RealPipelineRunner` to use a conservative default config or stubbed prompt so long as it does not hang and is clearly logged.

**Step 2 – Wire AppController to use PipelineRunner**
- Update `AppController.__init__` to accept a `pipeline_runner` parameter (with default `DummyPipelineRunner` if none is provided).
- Ensure `self.pipeline_runner` is set to either the provided runner or a default dummy instance.
- Ensure a fresh `CancelToken` is created on each `on_run_clicked` call.

**Step 3 – Fix lifecycle state transitions**
- Ensure the following invariants in `AppController`:
  - Initial state is `LifecycleState.IDLE`.
  - When `on_run_clicked` is invoked and no worker is running:
    - Lifecycle → `RUNNING`.
  - When the worker completes without error:
    - Lifecycle → `IDLE`.
  - When STOP is requested while running:
    - Lifecycle → `STOPPING` → then `IDLE` after pipeline exits.
  - When an exception occurs in the pipeline worker:
    - Lifecycle → `ERROR` (with `last_error` set) → then `IDLE` after the error has been surfaced/logged.

- Ensure that `threaded=False` mode (used by tests) executes these transitions synchronously without depending on tkinter’s `after` callbacks.

**Step 4 – Ensure GUI wiring reflects controller state**
- In `main_window_v2.py`, confirm that:
  - `run_button`, `stop_button`, `preview_button` are wired to `AppController` handlers.
  - `status_label` and log text area are updated via controller helper methods.
- Do not redesign the UI. Only ensure the new controller wiring is used.

**Step 5 – Add tests for controller/pipeline flow**
- Implement `tests/controller/test_app_controller_pipeline_flow_pr0.py` (see details in Section 9).
- Ensure tests:
  - Use `threaded=False` to avoid real threads.
  - Use a `FakePipelineRunner` that records calls, simulates work, and can raise exceptions on demand.

**Step 6 – Make sure a second run works**
- Add a dedicated test to verify:
  - First run completes.
  - Second run can start and complete.
  - No “previous worker still running” false positives if the first worker has already exited.

**Step 7 – Optional: Switch main entrypoint to new controller path**
- If and only if the current `src/main.py` is still using the older GUI/controller pairing that is known to be unstable, update it to use:
  - `MainWindow` from `main_window_v2.py`.
  - `AppController` with an appropriate `PipelineRunner`.

- Keep the wiring minimal:
  - Do not add new menus or dialogs.
  - Only ensure that pressing Run in the new GUI path exercises the same tested controller logic.

9. Required Tests (Failing First)
---------------------------------

Create `tests/controller/test_app_controller_pipeline_flow_pr0.py` with (at minimum) the following tests. They may initially fail until the implementation is completed.

1. `test_run_starts_pipeline_and_returns_to_idle`
   - Setup:
     - Create a Tk root (hidden), a `MainWindow`, and an `AppController` with:
       - `threaded=False`
       - `pipeline_runner=FakePipelineRunner()`
   - Action:
       - Call `controller.on_run_clicked()`.
   - Verify:
       - `FakePipelineRunner.run` was called exactly once.
       - `controller.state.lifecycle` is `LifecycleState.IDLE` at the end.
       - Log text includes markers like `"Starting pipeline"` and `"Pipeline completed"` (exact strings can be aligned with implementation).

2. `test_second_run_after_first_completes_succeeds`
   - Setup as above.
   - Action:
     - Call `on_run_clicked()` once, wait for sync execution to finish.
     - Call `on_run_clicked()` a second time.
   - Verify:
     - `FakePipelineRunner.run` called twice.
     - Lifecycle is `IDLE` after both runs.
     - No log entry indicates refusal to run due to “previous worker still running.”

3. `test_stop_sets_cancel_and_updates_lifecycle`
   - Setup as above but with a `FakePipelineRunner` that checks `cancel_token.is_cancelled()` inside its loop.
   - Action:
     - Start a run.
     - Call `on_stop_clicked()` during execution (in threaded=False mode this may mean the fake runner explicitly simulates a long-running task and checks `cancel_token`).
   - Verify:
     - `cancel_token.is_cancelled()` returns True inside the fake runner.
     - Lifecycle passes through `STOPPING` and ends in `IDLE`.
     - Log contains a message indicating a stop was requested.

4. `test_pipeline_error_sets_error_state_and_recovers`
   - Setup: `FakePipelineRunner` raises an exception when `run` is called.
   - Action: `on_run_clicked()`.
   - Verify:
     - Lifecycle transitions to `ERROR` and stores a non-empty `last_error`.
     - After the error is handled/logged, lifecycle returns to `IDLE` (in threaded=False this can be immediate).
     - Log contains an error marker `[controller] Pipeline error:` or equivalent.

10. Acceptance Criteria
-----------------------
This PR is accepted when:

- All tests in `tests/controller/test_app_controller_pipeline_flow_pr0.py` pass.
- Existing controller tests (if any) still pass.
- Pressing Run in the GUI (when wired to v2 controller path) results in:
  - Immediate log feedback that the pipeline started.
  - A clean completion (dummy or real) with no unhandled exceptions.
  - Ability to press Run again without restarting the app.
- There are no background thread tracebacks related to controller/pipeline wiring in the logs.

11. Rollback Plan
-----------------
If this PR introduces instability, revert by:

- Restoring previous versions of:
  - `src/controller/app_controller.py`
  - `src/gui/main_window_v2.py`
  - `src/main.py`
- Removing:
  - `src/controller/pipeline_runner.py`
  - `tests/controller/test_app_controller_pipeline_flow_pr0.py`

No data migrations are performed by this PR, so rollback is purely code-level.

12. Codex Execution Constraints
-------------------------------
- Do **not** modify any file outside the Allowed Files list.
- Do **not** redesign or restyle the GUI.
- Do **not** change the behavior or internals of the pipeline package (`src/pipeline`); only call it via a thin adapter.
- Always implement tests **first**, run them, confirm they fail, then implement the minimum code to make them pass.
- After changes, run at least:
  - `pytest tests/controller/test_app_controller_pipeline_flow_pr0.py -v`
  - `pytest tests/controller/test_app_controller.py -v` (if present)
- Display full test output so the human can verify.

13. Smoke Test Checklist
------------------------
After tests are green:

1. Launch StableNew in GUI mode.
2. Verify the GUI opens without errors.
3. Press Run:
   - Check that the log panel shows pipeline starting.
   - Check that the status bar reflects `Running` → `Idle`.
4. Press Run a second time:
   - Verify no hang, no crash, and logs show a second run.
5. Trigger a deliberate error (e.g., misconfigured API URL or intentionally raising inside RealPipelineRunner if wired):
   - Confirm a user-visible error log entry appears.
   - Confirm the app remains responsive after the error.
