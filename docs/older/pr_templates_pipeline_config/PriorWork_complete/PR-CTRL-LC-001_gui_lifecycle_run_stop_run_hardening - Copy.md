
# PR-CTRL-LC-001: GUI & Controller Lifecycle – Run / Stop / Run Hardening

## 1. Title

**PR-CTRL-LC-001: GUI & Controller Lifecycle – Run / Stop / Run Hardening**

---

## 2. Summary

This PR hardens the **GUI + controller lifecycle** around pipeline runs, with a specific focus on:

- **Run → Complete → Run again** behavior.
- **Run → Stop/Cancel → Run again** behavior.
- Ensuring that **only one pipeline run is active at a time** from the GUI’s point of view.
- Ensuring that **CancelToken and controller state transitions** behave consistently and are correctly reflected in the GUI controls.

This is a **behavioral stability** and **UX consistency** PR, not a refactor. It aims to:

- Add **tests** that cover the critical lifecycle transitions.
- Tighten **controller state management** (IDLE, RUNNING, STOPPING, ERROR).
- Ensure the GUI **never starts a second run** if the previous one is still active or in STOPPING.
- Ensure the GUI properly **re-enables controls** after runs complete or are canceled.

This PR assumes the repo is at the state of:

- `StableNew-MoreSafe-11-20-2025-07-27-00-AftrerPR-PIPE-CORE01.zip`

And referencing project docs:

- `docs/ARCHITECTURE_v2_Translation_Plan.md`
- `docs/StableNew_Roadmap_v1.0.md`
- `docs/Known_Bugs_And_Issues_Summary.md`
- `docs/GUI_FIGMA_LAYOUT_GUIDE.md`
- `docs/GUI_Component_Mapping.md`

---

## 3. Problem Statement

### 3.1 Symptoms & Known Issues

From prior runs and the Known Bugs summary, we have seen issues like:

- The pipeline **failing to start** after a previous run or error (“pipeline not running” despite pressing Run).
- Errors bubbling out of controller/pipeline into the GUI and leaving it in a **bad state** (e.g., `AttributeError` or `list has no attribute 'active'` causing a fatal error and requiring a restart).
- A lack of **clear state handling** for transitions:
  - IDLE → RUNNING
  - RUNNING → STOPPING
  - STOPPING → IDLE / ERROR
- GUI buttons and controls not always reflecting the **true underlying state** (e.g., Run button enabled when a run is still in progress, or Stop button remaining enabled after completion).

These issues make it difficult to:

- Reliably run multiple pipelines in one session.
- Confidently stop a run without leaving the app in limbo.
- Trust that the GUI’s controls reflect the actual lifecycle state.

### 3.2 Design Constraints (Architecture v2)

Architecture v2 requires:

- **GUI layer**:
  - UI-only (layout, widgets, event handlers).
  - Talks to the controller, not the pipeline directly.
  - Uses `root.after()` for thread-safe updates.

- **Controller layer**:
  - Owns lifecycle state (IDLE, RUNNING, STOPPING, ERROR).
  - Owns `CancelToken` and worker threads.
  - Validates config and launches pipeline in a worker thread.
  - Sends **state updates** back to GUI.

This PR exists to make sure the GUI + controller behavior matches these rules, especially around **Run / Stop / Run** sequences.

---

## 4. Goals

1. **Define explicit, test-covered lifecycle transitions** between IDLE, RUNNING, STOPPING, and ERROR in the controller.
2. Ensure that **only one pipeline run** can be started at a time from the GUI:
   - If a run is active or in STOPPING, clicking Run should be ignored or gracefully rejected.
3. Ensure **CancelToken** is created, owned, and cleared correctly per run:
   - New run = new token.
   - Stop/Cancel sets token and leads to STOPPING → IDLE/ERROR transitions.
4. Ensure the GUI’s **Run/Stop/control state** is correctly updated via controller callbacks:
   - Run button disabled while RUNNING/STOPPING.
   - Stop button enabled during RUNNING, disabled otherwise.
   - Appropriate status text / indicators for IDLE/RUNNING/STOPPING/ERROR.
5. Add **tests** for:
   - Run → Complete → Run again.
   - Run → Stop → Run again.
   - Error case: controller sets ERROR and GUI responds correctly.

---

## 5. Non-goals

- No redesign of the pipeline stages or executor (covered by pipeline-focused PRs).
- No change to randomizer/matrix or prompt logic.
- No GUI visual redesign beyond what is necessary for correct control enable/disable behavior.
- No changes to manifest schema or logging format (beyond optional minor log messages for lifecycle).

---

## 6. Allowed Files

Codex may modify **only** the following (or their equivalent paths if names differ slightly):

**Controller / Lifecycle Core**

- `src/controller/pipeline_controller.py`
- `src/controller/state.py` or `src/controller/*state*.py` (if present)

**GUI (minimal, strictly lifecycle wiring & controls)**

- `src/gui/main_window.py`
- `src/gui/pipeline_controls_panel.py`
- `src/gui/state.py` or `src/gui/*state*.py` (if present)
- `src/gui/api_status_panel.py` (only if needed to reflect lifecycle state; no layout changes)

**Tests**

- `tests/controller/test_pipeline_controller_lifecycle.py` (new)
- `tests/gui/test_pipeline_controls_lifecycle.py` (new)
- Existing controller or GUI tests that clearly relate to lifecycle, if they must be updated minimally to align with the new behavior.

**Docs**

- `docs/codex/prs/PR-CTRL-LC-001_gui_lifecycle_run_stop_run_hardening.md` (this file)
- Optional: a short entry in `docs/Known_Bugs_And_Issues_Summary.md` linking the lifecycle issue to this PR’s tests.

If any of these files are missing or named differently, ask for clarification instead of guessing.

---

## 7. Forbidden Files

Do **not** modify:

- Pipeline implementation:
  - `src/pipeline/executor.py`
  - Any `src/pipeline/*` stages (txt2img, img2img, upscale, etc.)

- Randomizer:
  - `src/utils/randomizer.py`
  - Any wildcard/matrix helper files.

- API Layer:
  - `src/api/client.py`

- Logging core:
  - `src/utils/structured_logger.py` or similar.

- Any `tools/`, `scripts/`, CI configuration, or `docs/` beyond this PR spec and a single line in Known Bugs (if needed).

Lifecycle behavior must be enforced through **controller and GUI** only.

---

## 8. Step-by-step Implementation

> **Important:** Follow TDD. Write failing tests first.

### 8.1 Define/Clarify Controller Lifecycle State

1. In `src/controller/pipeline_controller.py` (and/or `src/controller/state.py`):
   - Define or standardize lifecycle states: e.g., `IDLE`, `RUNNING`, `STOPPING`, `ERROR` (enum or constants).
   - Ensure the controller:
     - Starts in `IDLE`.
     - Transitions to `RUNNING` when a pipeline run starts.
     - Transitions to `STOPPING` when cancel/stop is requested.
     - Transitions to `IDLE` or `ERROR` when the worker thread completes or fails.

2. Ensure the controller owns a **per-run CancelToken**:
   - Created at the start of a run.
   - Exposed to the pipeline runner.
   - Cleared or replaced once the run completes or fails.

### 8.2 Controller Tests – Lifecycle

3. Create `tests/controller/test_pipeline_controller_lifecycle.py` with tests that:
   - Use a mock pipeline runner (no real WebUI calls).
   - Assert correct transitions for:
     - `IDLE → RUNNING → IDLE` on normal completion.
     - `IDLE → RUNNING → STOPPING → IDLE` on explicit cancel.
     - `IDLE → RUNNING → ERROR` on a simulated pipeline failure.

4. Add tests to ensure:
   - When in `RUNNING` or `STOPPING`, a **second call to “start run” is rejected** (e.g., returns False, raises a specific exception, or logs and no-ops) without starting a new worker thread.
   - The controller cleanly resets to `IDLE` and is able to start a **new run after completion or cancel**.

### 8.3 Wire GUI to Controller Lifecycle

5. In `src/gui/main_window.py` and `src/gui/pipeline_controls_panel.py`:

   - Ensure that GUI event handlers call **controller methods** like `start_run()`, `request_stop()`, etc., not pipeline directly.
   - Add or clarify callbacks from controller → GUI so that on lifecycle changes, the GUI:
     - Disables Run and enables Stop when entering `RUNNING`.
     - Shows a “Stopping…” or equivalent state during `STOPPING`.
     - Re-enables Run and disables Stop upon reaching `IDLE` or `ERROR`.
     - Displays an appropriate status message on `ERROR`.

6. Use `root.after()` or equivalent Tk-safe mechanisms for any callback that touches widgets.

### 8.4 GUI Tests – Lifecycle Behavior

7. Create `tests/gui/test_pipeline_controls_lifecycle.py`:

   - Use a minimal Tk root or a mock (existing GUI test patterns should be followed).
   - Use a stub or mock controller that exposes the lifecycle states and methods.
   - Tests should verify that:
     - When a run starts (controller goes to `RUNNING`):
       - Run button is disabled.
       - Stop button is enabled.
     - When Stop is requested and controller is `STOPPING`:
       - Run button stays disabled.
       - Stop may be disabled or remain enabled depending on current UX rules, but must be deterministic and documented.
     - When controller transitions to `IDLE` after completion or cancel:
       - Run button is re-enabled.
       - Stop button is disabled.
     - When controller transitions to `ERROR`:
       - GUI shows an error indication (status label / log message).
       - Run button is available for a new attempt.

### 8.5 Error Handling & Cleanup

8. In controller and/or GUI, ensure that unhandled exceptions from the worker thread:

   - Set controller state to `ERROR`.
   - Trigger an appropriate GUI update (status text, re-enabled Run button).
   - Do **not** leave the app in RUNNING/STOPPING indefinitely.

9. Add small, targeted log messages for lifecycle transitions (INFO-level) to assist diagnostics, but do not over-verbose the logs.

---

## 9. Required Tests (Failing First)

Before any implementation changes, create and run these tests so they fail on the current codebase:

1. `tests/controller/test_pipeline_controller_lifecycle.py::test_normal_run_transitions_idle_running_idle`
2. `tests/controller/test_pipeline_controller_lifecycle.py::test_cancel_transitions_idle_running_stopping_idle`
3. `tests/controller/test_pipeline_controller_lifecycle.py::test_error_transitions_idle_running_error`
4. `tests/controller/test_pipeline_controller_lifecycle.py::test_reject_second_run_while_running_or_stopping`
5. `tests/gui/test_pipeline_controls_lifecycle.py::test_buttons_reflect_running_state`
6. `tests/gui/test_pipeline_controls_lifecycle.py::test_buttons_and_status_after_cancel`
7. `tests/gui/test_pipeline_controls_lifecycle.py::test_buttons_and_status_after_error`

After they fail, implement the minimal changes required to make them pass.

Then run:

- `pytest tests/controller -v`
- `pytest tests/gui -v`
- `pytest -v` (full suite, time permitting)

Ensure all tests are green before considering this PR done.

---

## 10. Acceptance Criteria

This PR is complete when:

1. All new tests in `tests/controller/test_pipeline_controller_lifecycle.py` and `tests/gui/test_pipeline_controls_lifecycle.py` are passing.
2. Existing controller and GUI tests remain passing or are updated minimally where lifecycle expectations were ambiguous.
3. Manual testing confirms:
   - Run → Complete → Run again works reliably without requiring an app restart.
   - Run → Stop → Run again works reliably without leaving the app in a weird state.
   - GUI controls (Run/Stop) and status indicators always reflect the true lifecycle state.
4. If a pipeline error occurs, the GUI:
   - Shows an error indication.
   - Returns to a usable state where the user can start a new run.
5. No modifications have been made outside the explicitly allowed files.

---

## 11. Rollback Plan

If regressions occur:

1. Revert changes to:
   - `src/controller/pipeline_controller.py` (and any related controller state file).
   - `src/gui/main_window.py`
   - `src/gui/pipeline_controls_panel.py`
   - New tests in `tests/controller/test_pipeline_controller_lifecycle.py`
   - New tests in `tests/gui/test_pipeline_controls_lifecycle.py`
2. Remove any related notes from `docs/Known_Bugs_And_Issues_Summary.md` that reference PR-CTRL-LC-001.
3. Re-run the test suite to ensure it returns to the previous known-good state.

---

## 12. Codex Execution Constraints

**For Codex (Implementer):**

- Open this spec at:
  - `docs/codex/prs/PR-CTRL-LC-001_gui_lifecycle_run_stop_run_hardening.md`

Constraints:

1. **Do not modify** any files outside the **Allowed Files** list.
2. **Do not refactor** beyond what’s required to pass the lifecycle tests.
3. Implement **TDD-first**:
   - Create the new tests.
   - Run them and capture failing output.
   - Only then adjust controller/GUI code.
4. After implementation:
   - Run:
     - `pytest tests/controller -v`
     - `pytest tests/gui -v`
     - `pytest -v` (if feasible)
   - Paste the **full test output** back for review.
5. If file paths differ from what’s listed, ask for confirmation before proceeding.

---

## 13. Smoke Test Checklist

After all tests pass, perform these manual checks in a GUI session:

1. **Run → Complete → Run again**
   - Configure a simple txt2img-only pipeline.
   - Click Run, let it complete.
   - Click Run again with the same settings.
   - Confirm:
     - No errors.
     - Run and Stop buttons behave consistently.
     - Status text updates correctly.

2. **Run → Stop → Run again**
   - Start a longer-running pipeline (e.g., multiple images).
   - Click Stop while it’s in progress.
   - Wait for it to reach a stable state (IDLE or ERROR).
   - Click Run again.
   - Confirm the pipeline starts cleanly and controls behave as expected.

3. **Error Handling**
   - Simulate an error condition (e.g., misconfigured WebUI URL, or using a known failing API mock in dev).
   - Confirm:
     - GUI shows an error state.
     - Run becomes available again once the error is surfaced.
     - No stuck RUNNING/STOPPING states.

4. **Rapid User Interaction**
   - While a run is active, click Run again several times.
   - Confirm:
     - No second worker thread is started.
     - GUI either ignores the clicks or shows a subtle indication (“Already running”).

If all smoke tests pass and the tests are green, this PR’s lifecycle hardening can be considered complete.
