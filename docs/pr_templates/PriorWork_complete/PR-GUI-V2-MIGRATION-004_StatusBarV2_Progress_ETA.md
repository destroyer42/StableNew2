# PR-GUI-V2-MIGRATION-004 – Wire StatusBarV2 to Progress & ETA Callbacks (GUI V2)

## 1. Title

Wire StatusBarV2 to Progress & ETA Callbacks (GUI V2)

## 2. Summary

This PR connects the existing `StatusBarV2` panel to StableNew’s GUI V2 lifecycle by wiring progress and ETA callbacks into the status bar in a thread-safe way. It keeps all logic on the GUI side (no controller/pipeline changes) and validates the behavior with a focused `tests/gui_v2` suite that simulates controller callbacks via a dummy controller.

After this PR:

- `StatusBarV2` owns status text, progress bar, and ETA display.
- `StableNewGUI` exposes small handler methods that update the status bar in response to pipeline progress and lifecycle changes.
- The new V2 tests verify that progress/ETA callbacks invoked by a dummy controller update the status bar correctly.

## 3. Problem Statement

Right now, the V2 GUI shell has:

- A scaffolded `StatusBarV2` panel.
- A working “Run” button and controller wiring.
- A V2 pipeline config panel that round‑trips txt2img fields into the controller config.

However, **there is no live feedback loop** tied into the status bar:

- Users can’t see when a run is “running” vs “idle”.
- The progress bar and ETA are not being driven by controller callbacks.
- There is no tested contract for how the GUI should react to progress/lifecycle updates.

We need to establish a clear, GUI‑only contract that connects future controller callbacks to visible status/ETA updates in V2, without touching the pipeline or controller internals yet.

## 4. Goals

1. Wire `StatusBarV2` to handle:
   - Status text (Idle/Running/Completed/Error).
   - Progress value (0–100).
   - ETA text (e.g., “ETA: 00:10”).
2. Add GUI‑side handler methods on `StableNewGUI` to receive progress and lifecycle events:
   - `StableNewGUI._on_pipeline_progress(...)`
   - `StableNewGUI._on_pipeline_state_change(...)`
   These methods must update `StatusBarV2` via `root.after` for Tkinter thread safety.
3. Ensure the dummy controller in `tests/gui_v2` can register callbacks and simulate progress/lifecycle events that drive the status bar.
4. Provide a dedicated V2 test module that:
   - Asserts initial status bar state on startup.
   - Asserts that simulated progress callbacks update the progress bar and ETA label.
   - Asserts that simulated lifecycle callbacks change the status text appropriately.

## 5. Non-goals

- No changes to real controller or pipeline behavior.
- No changes to how the real pipeline computes progress or ETA.
- No changes to the legacy V1 GUI tests or layout.
- No new threading or worker logic; we only handle callbacks and UI updates.
- No changes to logging, manifests, or `StructuredLogger`.

## 6. Allowed Files

You may modify or create ONLY the following files:

- `src/gui/status_bar_v2.py`
- `src/gui/main_window.py`
- `tests/gui_v2/conftest.py`
- `tests/gui_v2/test_gui_v2_status_bar_progress_eta.py` (new)

If you believe another file must change, STOP and report instead of editing it. That would require a separate PR.

## 7. Forbidden Files

You MUST NOT modify:

- `src/controller/**`
- `src/pipeline/**`
- `src/api/**`
- `src/utils/**`
- `src/gui_v1/**` (if present)
- `tests/gui_v1_legacy/**`
- Any test files outside `tests/gui_v2/**`
- Any CI/tooling configs or scripts

## 8. Step-by-step Implementation

### 8.1 Enhance StatusBarV2

**File:** `src/gui/status_bar_v2.py`

1. Ensure `StatusBarV2` is a `ttk.Frame` (or similar) that owns:
   - A status `ttk.Label` (e.g., `self.status_label`).
   - A `ttk.Progressbar` (e.g., `self.progress_bar`) configured for 0–100 range.
   - An ETA `ttk.Label` (e.g., `self.eta_label`).

2. Implement public methods on `StatusBarV2`:

   - `set_idle(self) -> None`  
     - Sets status text to `"Idle"`.
     - Resets progress bar to `0`.
     - Clears ETA text.

   - `set_running(self) -> None`  
     - Sets status text to `"Running..."`.
     - Leaves progress value unchanged (or sets to 0 if you prefer), but does not clear ETA automatically.

   - `set_completed(self) -> None`  
     - Sets status text to `"Completed"`.

   - `set_error(self, message: str | None = None) -> None`  
     - Sets status text to `"Error"` or `"Error: {message}"` if a message is provided.

   - `update_progress(self, fraction: float | None = None) -> None`  
     - Accepts `fraction` in `[0.0, 1.0]`.  
     - If `fraction` is `None`, treat as 0.0.  
     - Maps fraction to progress bar `value` in `[0, 100]` (e.g., `fraction * 100`).  
     - Clamp out‑of‑range values into `[0, 1]` defensively.

   - `update_eta(self, seconds: float | None = None) -> None`  
     - If `seconds` is `None`, clear ETA text.  
     - Otherwise, format as `ETA: mm:ss` using integer minutes/seconds, and set `self.eta_label["text"]` to that value.

3. Theme integration: reuse whatever theme tokens already exist (e.g., ASWF colors) but **do not** introduce new global theme dependencies. Keep all styling local to this file and safe for tests.

### 8.2 Add GUI handler methods on StableNewGUI

**File:** `src/gui/main_window.py`

1. In `StableNewGUI.__init__` / `_build_ui`, ensure:

   - A `StatusBarV2` instance is created and stored as `self.status_bar_v2` (this should already exist from prior PRs).  
   - After constructing the GUI, call `self.status_bar_v2.set_idle()` so the initial state is consistent and testable.

2. Implement two private handler methods on `StableNewGUI`:

   - `_on_pipeline_progress(self, progress: float | None = None, total: float | None = None, eta_seconds: float | None = None) -> None`  
     Behavior:
     - Compute a fraction if possible (e.g., if both `progress` and `total` are non‑zero, use `fraction = progress / total`; otherwise, treat `fraction` as `None` and let the status bar default to 0).  
     - Schedule a Tk‑safe update via `self.root.after(0, ...)` that calls:  
       - `self.status_bar_v2.update_progress(fraction)`  
       - `self.status_bar_v2.update_eta(eta_seconds)`

   - `_on_pipeline_state_change(self, state: str) -> None`  
     Behavior:
     - Map `state` (case‑insensitive) into one of: `"idle"`, `"running"`, `"completed"`, `"error"`.  
       For example:
       - `"IDLE"` or `"idle"` → `set_idle()`  
       - `"RUNNING"` / `"STARTED"` / `"BUSY"` → `set_running()`  
       - `"COMPLETED"` / `"DONE"` / `"SUCCESS"` → `set_completed()`  
       - `"ERROR"` / `"FAILED"` → `set_error()`  
     - Schedule this via `self.root.after(0, ...)` to call the appropriate `StatusBarV2` method.

3. **Important:** Both handlers must be safe when called from non‑GUI threads (controller worker threads). `root.after` is required; do not directly modify widgets outside `after` callbacks.

### 8.3 Register callbacks with the controller (soft wiring)

We will **not** change the real controller, but we’ll offer a soft registration path that works when the controller exposes a progress API.

**File:** `src/gui/main_window.py`

1. Add a small helper method on `StableNewGUI`, e.g.:

   ```python
   def _wire_progress_callbacks(self) -> None:
       controller = self.controller
       if controller is None:
           return

       callbacks = {
           "on_progress": self._on_pipeline_progress,
           "on_state_change": self._on_pipeline_state_change,
       }

       for name in ("configure_progress_callbacks", "register_progress_callbacks", "set_progress_callbacks"):
           method = getattr(controller, name, None)
           if callable(method):
               try:
                   method(**callbacks)
               except TypeError:
                   # Controller may accept a subset of callbacks; use kwargs so it can ignore extra keys.
                   method(**{k: v for k, v in callbacks.items() if k in method.__code__.co_varnames})
               break
   ```

2. Call `_wire_progress_callbacks()` at the end of GUI initialization, after `self.controller` is set and after `self.status_bar_v2` has been created.

3. This helper is defensive:
   - If the real controller doesn’t implement any of these methods, nothing happens.  
   - Tests will use a dummy controller that does implement one of them.

### 8.4 Extend DummyController for GUI V2 tests

**File:** `tests/gui_v2/conftest.py`

1. Update/extend `DummyController` to support progress callback registration.

   - Add something like:

     ```python
     class DummyController:
         def __init__(self, ...):
             self.progress_callbacks = {}

         def configure_progress_callbacks(self, **callbacks):
             self.progress_callbacks.update(callbacks)
     ```

   - Ensure that whatever method name you choose (`configure_progress_callbacks` is recommended) matches one of the names probed in `_wire_progress_callbacks`.

2. Provide a fixture (or extend the existing `gui_app_with_dummies` fixture) so that tests can:

   - Access the created `DummyController` instance.
   - Access `controller.progress_callbacks` to trigger callbacks manually.

### 8.5 New GUI V2 tests for StatusBarV2

**File:** `tests/gui_v2/test_gui_v2_status_bar_progress_eta.py` (new)

Create tests that assume:

- A Tk root can be created; if not, skip with `pytest.skip` and a clear message.
- `gui_app_with_dummies` yields a tuple `(gui, controller)` or provides access to `gui` and `controller` via fixtures.

Tests to add:

1. `test_status_bar_initial_state`

   - Build the GUI via the V2 fixture.
   - Assert:
     - `gui.status_bar_v2.status_label["text"]` is `"Idle"`.
     - `gui.status_bar_v2.progress_bar["value"] == 0` (or close to 0).
     - `gui.status_bar_v2.eta_label["text"]` is empty or a known default (e.g., `""`).

2. `test_progress_callback_updates_progress_and_eta`

   - Build GUI and obtain `controller` and its `progress_callbacks`.
   - Retrieve the progress callback (e.g., `cb = controller.progress_callbacks["on_progress"]`).
   - Call `cb(progress=5, total=10, eta_seconds=30)`.
   - Use `gui.root.update_idletasks()` if needed to flush `after` callbacks.
   - Assert:
     - Progress bar `value` is about `50` (allowing for float normalization).  
     - ETA label text equals `"ETA: 00:30"`.

3. `test_state_change_callback_updates_status_text`

   - Retrieve the state change callback (e.g., `cb = controller.progress_callbacks["on_state_change"]`).
   - Call `cb("RUNNING")`; flush events; assert status text is `"Running..."`.
   - Call `cb("COMPLETED")`; flush events; assert status text is `"Completed"`.
   - Optionally call `cb("ERROR")`; assert `"Error"` is present in the status label text.

Keep all tests deterministic and avoid sleeps; rely on `root.update()` or `root.update_idletasks()` after invoking callbacks.

## 9. Required Tests (Failing First)

Before implementing code, add the new test module and let it fail:

1. Add `tests/gui_v2/test_gui_v2_status_bar_progress_eta.py` with the tests described above, referencing `gui.status_bar_v2` and controller `progress_callbacks`.
2. Run:
   - `pytest tests/gui_v2/test_gui_v2_status_bar_progress_eta.py -v` → expect failures because:
     - `StatusBarV2` may not expose the required methods/properties yet.
     - `StableNewGUI` may not wire callbacks or initialize status correctly.

Then implement the code until all tests pass.

## 10. Acceptance Criteria

This PR is complete when:

1. `StatusBarV2`:
   - Owns status, progress, and ETA widgets.
   - Implements `set_idle`, `set_running`, `set_completed`, `set_error`, `update_progress`, and `update_eta` as described.
2. `StableNewGUI`:
   - Initializes the status bar to the “Idle” state on startup.
   - Exposes `_on_pipeline_progress` and `_on_pipeline_state_change` that update the status bar via `root.after`.
   - Attempts to register progress callbacks on the controller using a defensive helper without raising errors if no such API exists.
3. `DummyController` in `tests/gui_v2/conftest.py`:
   - Captures progress/lifecycle callbacks in a dict so tests can invoke them.
4. GUI V2 tests:
   - `tests/gui_v2/test_gui_v2_status_bar_progress_eta.py` passes.
   - Existing GUI V2 tests (`test_gui_v2_layout_skeleton.py`, `test_gui_v2_pipeline_button_wiring.py`, `test_gui_v2_pipeline_config_roundtrip.py`, `test_gui_v2_startup.py`) still pass.
5. Global tests:
   - `pytest tests/gui_v2 -v` passes.
   - `pytest -v` passes with V2 tests included, aside from any existing known skips related to Tk/Tcl availability.
6. No forbidden files were modified.

## 11. Rollback Plan

If regressions occur:

1. Revert changes to:
   - `src/gui/status_bar_v2.py`
   - `src/gui/main_window.py`
   - `tests/gui_v2/conftest.py`
   - `tests/gui_v2/test_gui_v2_status_bar_progress_eta.py`
2. Re-run:
   - `pytest tests/gui_v2 -v`
   - `pytest -v`
3. Confirm that the suite returns to the prior state (status bar exists but is not wired to progress/ETA).

## 12. Codex Execution Constraints

- Do NOT modify any files outside the **Allowed Files** list.
- Do NOT touch controller, pipeline, API, or utils layers.
- Keep all logic GUI-side and deterministic.
- Use `root.after` for all widget updates that might be triggered from non‑GUI threads.
- Prefer small, composable methods; avoid large refactors or new abstractions.
- If you hit an unexpected controller API mismatch, handle it defensively (e.g., via `hasattr`) and report it rather than forcing a change in controller code.

## 13. Smoke Test Checklist

After implementation, perform this minimal manual smoke test (if your environment permits running the GUI):

1. Launch StableNew in a way that reaches the V2 GUI.
2. Confirm:
   - Status bar shows “Idle” initially.
   - Progress bar is empty (0).
   - ETA is blank.
3. Trigger a dummy or short pipeline run (if available); visually verify that:
   - Status text changes to something “running‑like”.
   - Progress bar advances.
   - ETA text appears and updates.
4. Close the app and check that no exceptions were printed related to status bar callbacks or Tkinter thread usage.

If GUI cannot be launched in your environment, rely on the automated tests as the sole verification mechanism.
