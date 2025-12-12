Title
PR-GUI-033_thread_safety_and_state — Fix GUI thread-safety and lifecycle transitions

Summary
This PR fixes three related issues introduced during GUI test-mode and error-handling refactors:

A background “check” thread (check_in_thread) reads api_url_var (a tk.StringVar) from outside the Tk main thread, causing RuntimeError: main thread is not in main loop in live runs.

StableNewGUI.on_error no longer reliably drives the GUI state to GUIState.ERROR when invoked from a worker thread, causing tests/gui/test_gui_thread_marshaling.py::test_pipeline_error_marshaling to fail.

The cancel path and/or controller wiring no longer guarantees a transition from RUNNING → IDLE with a “ready” status, causing tests/gui/test_main_window_pipeline.py::test_cancel_transitions_to_idle_with_ready_status to hang and matching the real-world “freeze” when trying to run a pipeline.

The PR restores:

Proper Tk thread-safety for background checks.

Deterministic GUIState.ERROR transitions for worker-thread errors, even when dialogs are suppressed.

Deterministic RUNNING → IDLE transitions and a ready status after cancel, consistent with the tests’ expectations.

Goals

check_in_thread (and any similar worker) must not touch Tk variables or widgets.

StableNewGUI.on_error called from any thread must always result in state_manager.state == GUIState.ERROR, while still honoring test-mode dialog suppression.

Cancel must reliably transition the GUI back to IDLE and show the “ready” status used in test_cancel_transitions_to_idle_with_ready_status.

Make tests/gui/test_gui_thread_marshaling.py and tests/gui/test_main_window_pipeline.py::test_cancel_transitions_to_idle_with_ready_status pass without hangs.

Non-goals

No changes to pipeline core behavior (that’s covered by the PIPE PRs).

No changes to CancelToken semantics in the pipeline layer.

No changes to how WebUI discovery or launch works other than making check threads safe.

No major redesign of the state machine — just make existing semantics reliable.

Allowed files

src/gui/main_window.py

src/gui/state.py (only for StateManager / GUIState / state-proxy fixes)

tests/gui/test_gui_thread_marshaling.py (only if absolutely required for signature adjustments, but try to keep behavior unchanged)

tests/gui/test_main_window_pipeline.py (only for minor fixture adjustments if the GUI API changed; do not change core assertions about RUNNING → IDLE and status text)

Forbidden files

src/controller/... (logic / lifecycle should not be rewritten here)

src/pipeline/...

Randomizer / logger / config files

Build / project config

Step-by-step implementation

A) Fix check_in_thread Tk misuse

In src/gui/main_window.py, find check_in_thread (line ~3220 in your log) and the place where its thread is started.

Refactor so:

api_url_var.get() is called on the main thread, before the thread is spawned.

The worker thread receives a plain string argument (e.g., api_url) and never touches Tk variables or widgets.

Example shape (conceptual, not exact code):

def _start_api_check(self):

raw = self.api_url_var.get() (Tk main thread)

api_url = self._normalize_api_url(raw)

threading.Thread(target=self.check_in_thread, args=(api_url,), daemon=True).start()

def check_in_thread(self, api_url: str):

No self.api_url_var.get() inside this method.

Only use the passed api_url.

Ensure any other background threads follow the same pattern (no Tk calls outside main thread).

B) Make error marshaling always drive GUIState.ERROR

In src/gui/main_window.py, revisit StableNewGUI.on_error and its helper(s).

The desired behavior:

From any thread, on_error(exc) must:

Schedule a main-thread handler (via root.after or similar), OR if you already decided to set state immediately, then:

Set state_manager.state = GUIState.ERROR in a thread-safe way that doesn’t depend on dialogs.

The main-thread handler (or the same on_error) must:

Always transition the state to GUIState.ERROR (or call the correct StateManager API).

Only conditionally show dialogs depending on:

STABLENEW_NO_ERROR_DIALOG

GUI test mode.

Concretely:

Do not guard the state transition behind if is_gui_test_mode() or if STABLENEW_NO_ERROR_DIALOG; only guard the dialog.

Double-check that:

The path taken when enable_gui_test_mode() and STABLENEW_NO_ERROR_DIALOG=1 are set still sets the StateManager to ERROR.

Then re-run:

pytest tests/gui/test_gui_thread_marshaling.py::test_pipeline_error_marshaling -v

C) Fix cancel → IDLE transition and ready status

In src/gui/main_window.py, locate:

The handler wired to the Cancel button (something like _on_cancel_clicked).

The callbacks from the controller or pipeline that report pipeline completion, cancellation, and/or state.

Ensure there is a clear, single place where “cancel complete” leads to:

state_manager.state becoming GUIState.IDLE.

The GUI status bar / “ready” text being set to the value expected by test_cancel_transitions_to_idle_with_ready_status (use the test as the source of truth).

It is okay if the implementation treats cancel and “natural finish” slightly differently, but after cancel you must end up in IDLE with the ready status.

Common pattern:

Controller calls a GUI callback like on_pipeline_cancelled() on the main thread:

Sets state to IDLE.

Updates status line to “Ready” / “Ready (idle)” / whatever the test expects.

Ensures any “Run/Cancel” buttons toggle back to “Run”.

If GUI test mode introduced a special “deterministic progress callback wiring hook”, make sure it does not bypass this cancel callback in normal runs or tests.

Then re-run:

pytest tests/gui/test_main_window_pipeline.py::test_cancel_transitions_to_idle_with_ready_status -v

Required tests

pytest tests/gui/test_gui_thread_marshaling.py::test_pipeline_error_marshaling -v

pytest tests/gui/test_main_window_pipeline.py::test_cancel_transitions_to_idle_with_ready_status -v

Then:

pytest tests/gui -v

pytest

Acceptance criteria

No more RuntimeError: main thread is not in main loop from check_in_thread during live runs or tests.

test_gui_thread_marshaling passes and verifies:

Worker-thread error → state goes to GUIState.ERROR without blocking dialogs in test mode.

test_main_window_pipeline::test_cancel_transitions_to_idle_with_ready_status passes without hanging.

Running the GUI:

The app does not freeze on Run.

Cancel returns the UI to IDLE with appropriate “ready” status.