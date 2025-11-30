PR-046 — Robust App Shutdown (D-08 Implementation, V2-P1)

PR-ID: PR-046
Risk Tier: High (lifecycle + process management, reachable from src/main.py)
Goal: Ensure a single, deterministic shutdown path that reliably tears down the Tk GUI, cancels pipeline work, and terminates the Stable Diffusion WebUI process, regardless of how the app exits (window “X”, Exit button, or error path).

1. Baseline & Constraints

Baseline snapshot: StableNew-snapshot-20251130-075449.zip (with repo_inventory.json)

Active lifecycle-related modules:

src/main.py (entrypoint)

src/app_factory.py (GUI app wiring)

src/controller/app_controller.py (GUI lifecycle owner)

src/controller/webui_connection_controller.py

src/api/webui_process_manager.py

src/gui/gui_invoker.py, src/gui/main_window_v2.py, src/gui/layout_v2.py (Tk root & view wiring)

Architecture constraints:

GUI → Controller → Pipeline → API only (strict downward deps)

Controller owns lifecycle & threading

executor.py and webui_process_manager.py are “holy relics” — changes must be surgical and well-tested

2. Problem Statement

Current behavior:

Closing the GUI (via window “X” or test harness) leaves:

The main Python app process still resident.

A separate Stable Diffusion WebUI Python process still running.

Repeated GUI launches (especially under tests) accumulate:

Multiple orphaned WebUI processes.

1.6+ GB of RAM eaten over time.

This leads to:

Out-of-memory conditions during test runs.

Flaky behavior if stale WebUI processes are still bound to ports / resources.

There is no single, authoritative shutdown contract; bits of cleanup are scattered among GUI, controller, and API layers.

We need a single “app shutdown” path that runs on every exit and guarantees “no leftover work” at the process level.

3. Scope

In-scope (behavioral changes):

Centralized shutdown contract

Introduce an explicit lifecycle API in controller layer, e.g.:

AppController.shutdown_app(reason: str | None = None) -> None

Responsibilities:

Cancel any active pipeline / queue execution.

Flush/close learning/recording hooks (if they register with controller).

Instruct WebUI process manager to stop the WebUI server and wait for termination.

Ensure no new GUI callbacks fire after shutdown has started.

WebUI process cleanup

Extend webui_process_manager with a robust, idempotent stop contract:

e.g. stop_webui(grace_seconds: float = 10.0) -> bool

Behavior:

If WebUI not running → return True immediately.

If running:

Send graceful stop (existing mechanism if present).

Wait up to grace_seconds.

If still alive, escalate to hard kill (proc.kill() or equivalent).

Mark internal state as stopped so double-calls are safe.

GUI / Tk lifecycle

Ensure the Tk root uses a single callback for closure:

Bind WM_DELETE_WINDOW to a handler (e.g. on_app_close) that:

Calls app_controller.shutdown_app("window-close") exactly once.

Then calls root.destroy() once the controller shutdown path returns (or at least has initiated cleanup).

Any explicit “Exit”/“Quit” menu item or button must delegate to the same handler.

Main / test harness interaction

Make sure the path used by src/main.py or any GUI runner:

Does not bypass the centralized shutdown contract.

Uses try/finally or equivalent so that if the event loop unwinds due to an exception, shutdown_app("exception") still runs.

Out-of-scope (explicit non-goals):

No changes to:

src/pipeline/executor.py

src/pipeline/pipeline_runner.py

Pipeline stage semantics or config structures.

No new threading model; this PR only coordinates existing threads/processes.

No changes to GUI layout or design system (PR-041/041A already cover theme/layout).

4. Allowed Files

Controller / factory / lifecycle wiring

src/app_factory.py

src/controller/app_controller.py

src/controller/webui_connection_controller.py (only for exposing/using existing WebUI control methods)

src/gui/gui_invoker.py (if this is where Tk root is started / run loop is invoked)

src/gui/main_window_v2.py (wiring only: callbacks, WM_DELETE_WINDOW, Exit button(s))

src/gui/layout_v2.py (only if needed to connect the close handler to the view tree)

API layer (process management)

src/api/webui_process_manager.py (surgical changes, see Implementation Outline)

Optional / minimal

src/main.py — only if absolutely required to add a try/finally that calls into controller lifecycle. If so, changes must be tiny and clearly documented.

5. Forbidden Files

Do not modify:

src/pipeline/executor.py

src/pipeline/pipeline_runner.py

src/pipeline/stage_sequencer.py

Any learning/* modules (beyond calling existing hooks via controller)

Any V1 GUI files (e.g., src/gui/main_window.py, archived V1 panels)

Any design-system PR files (theme_v2.py, design_system_v2.py, etc.) already covered by PR-041/041A.

If you discover a required change to a forbidden file, stop and mark it as a follow-on PR (e.g., PR-048 — Executor shutdown hooks).

6. Implementation Outline
6.1 Add a controller-level shutdown contract

In src/controller/app_controller.py:

Add an instance-level sentinel, e.g. _is_shutting_down: bool = False.

Add:

def shutdown_app(self, reason: str | None = None) -> None:
    if self._is_shutting_down:
        return
    self._is_shutting_down = True

    # 1) Cancel any running pipelines/queue
    try:
        self._cancel_active_jobs(reason or "shutdown")
    except Exception:
        logging.exception("Error cancelling active jobs during shutdown")

    # 2) Close/detach learning hooks (if any)
    try:
        self._shutdown_learning_hooks()
    except Exception:
        logging.exception("Error shutting down learning hooks")

    # 3) Instruct WebUI to stop
    try:
        self._shutdown_webui()
    except Exception:
        logging.exception("Error shutting down WebUI")


Implement helper methods such as:

_cancel_active_jobs(...) using existing JobService / runner / cancel-token APIs (do not touch executor core).

_shutdown_learning_hooks() if learning controller or sidecars are registered with the app controller.

_shutdown_webui() which delegates to webui_connection_controller or directly to webui_process_manager via the proper public API.

Note: new helpers should be private and small; they should only orchestrate existing primitives, not reinvent them.

6.2 Harden webui_process_manager

In src/api/webui_process_manager.py:

Introduce a robust stop function, e.g.:

def stop_webui(grace_seconds: float = 10.0) -> bool:
    """
    Attempt to gracefully stop the WebUI process. Returns True if the process is
    confirmed not running at the end (either because it never started or was terminated).
    """


Behavior:

If no process handle / PID is registered → return True.

If process is present:

If it has already finished, clean up handle and return True.

Otherwise:

Send the existing graceful shutdown signal (whatever start logic uses — SIGINT, HTTP API call, etc.).

Wait up to grace_seconds for it to exit.

If still alive, call proc.kill() and wait again (short timeout).

Ensure that internal state is updated so subsequent calls are essentially no-ops.

Ensure idempotency:

Repeated calls should not raise exceptions if the process has already gone.

Use try/except with logging for OS-level errors (e.g., “No such process”).

6.3 Bind GUI close events to the shutdown contract

In whichever module owns the Tk root (likely src/app_factory.py and src/gui/main_window_v2.py):

Ensure there is a single on_app_close function that:

def on_app_close() -> None:
    app_controller.shutdown_app("window-close")
    root.after_idle(root.destroy)  # ensure destroy is on Tk event loop


Wire it to:

root.protocol("WM_DELETE_WINDOW", on_app_close)

Any “Exit” / “Quit” action in menus or toolbar (if present).

Ensure this handler is only registered once and doesn’t cause recursion (no nested root.quit() vs root.destroy() wars).

If src/gui/gui_invoker.py is the main entry point for Tk:

Ensure it uses the same on_app_close callback; do not create multiple independent shutdown paths.

6.4 Optional: Main entrypoint safety

If current src/main.py wraps GUI invocation without a finally:

Minimal change sketch:

def main() -> None:
    controller = build_app_controller()  # via app_factory
    try:
        run_gui(controller)
    finally:
        # Belt-and-suspenders: if GUI exit path failed, enforce shutdown here.
        controller.shutdown_app("main-finally")


This must only be added if it does not conflict with the Tk shutdown pattern (no double-destroys). Make shutdown_app idempotent to allow both the GUI close handler and main’s finally-block to call it safely.

7. Definition of Done

PR-046 is complete when:

Single shutdown path

There is an explicit shutdown_app(...) contract in AppController.

All GUI exit points (WM close, Exit button) call this contract.

WebUI termination

stop_webui(...) in webui_process_manager exists and:

Returns True when WebUI is not running.

Attempts graceful stop then hard kill when necessary.

shutdown_app calls WebUI shutdown once.

Idempotency

Multiple calls to the shutdown path (e.g., WM close + test harness) do not raise errors or double-kill.

No observed zombie processes

After closing the app, you can restart the GUI multiple times in a row without accumulating WebUI or extra Python processes.

No regressions

App still boots from src/main.py.

Pipelines still run successfully.

Existing WebUI launch behavior remains functionally equivalent when the app is running.

8. Tests to Run (for PR-046)

Use existing tests as-is (PR-047 will add new ones):

Any existing API / WebUI tests (if present), e.g.:

pytest tests/api/test_webui_process_manager*.py -q (or equivalent)

Core GUI / journey subset (as defined in Phase 1):

pytest $(cat tests/phase1_test_suite.txt) -q (if that file exists as in other PRs)