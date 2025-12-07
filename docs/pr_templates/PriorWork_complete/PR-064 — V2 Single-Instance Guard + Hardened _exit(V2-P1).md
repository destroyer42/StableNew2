PR-064 — V2 Single-Instance Guard + Hardened _graceful_exit() (V2-P1)
Summary

Even after PR-057 → PR-063, the shutdown journey test still fails because the StableNew parent process does not always terminate within the expected window, even when:

WebUI shutdown is initiated and (sometimes) completes

Auto-exit mode is enabled

The GUI logs appear to reach a sensible end

This PR ports the proven V1 lifecycle pattern into the V2 entrypoint:

A single-instance guard using a localhost socket lock in src/main.py.

A centralized _graceful_exit() that:

Stops the controller and worker threads

Shuts down SD-WebUI and its process tree

Destroys Tk / GUI

Runs the shutdown inspector (PR-061) if enabled

As a last resort, calls os._exit(0) when the process fails to terminate cleanly

The goal is to ensure that every exit path (X button, Exit command, auto-exit, fatal error) routes through a single, hardened exit function that guarantees the interpreter terminates, eliminating zombie python.exe after GUI close.

Goals

Reintroduce the single-instance socket lock at the V2 entrypoint to avoid multiple GUIs competing for resources and confusing shutdown.

Define a single _graceful_exit() function in the V2 entry path that:

Performs orderly shutdown of controller, threads, and WebUI

Cleans up Tk resources

Runs shutdown instrumentation (PR-061) when configured

Terminates the process via os._exit(0) if the interpreter is still alive after a short watchdog period

Ensure that:

on_app_close / Exit button

Auto-exit (PR-062)

Fatal-error / unrecoverable path
all ultimately call _graceful_exit() instead of ad-hoc shutdown sequences.

Make the shutdown journey test (test_shutdown_relaunch_leaves_no_processes) pass reliably by ensuring the subprocess always terminates within the allotted timeout window.

Scope & Risk Tier

Subsystems: Entry point, GUI lifecycle, shutdown behavior.

Risk tier: High (main entry + process lifecycle), but constrained:

No changes to pipeline executor

No changes to business logic or payloads

Focused on startup/teardown only

Allowed Files

Code changes are restricted to:

src/main.py

src/controller/app_controller.py

src/gui/main_window_v2.py (only to tighten close/exit wiring to _graceful_exit)

src/utils/single_instance.py (NEW helper module for socket lock)

src/utils/graceful_exit.py (NEW helper module if needed to keep logic centralized)

tests/journeys/test_shutdown_no_leaks.py (tiny updates if test needs to call new exit hooks explicitly)

Forbidden Files

Do not touch:

src/pipeline/executor.py

src/api/webui_process_manager.py (already addressed in PR-057)

Any learning / randomizer modules

Any non-GUI V2 view panels (pipeline tab, etc.)

If shutdown inspector behavior needs tweaks, do so through the public hook exposed in PR-061, not by rewriting its internals here.

Background & Prior Art

From the historical docs:

V1 solved a similar zombie-process problem with a localhost socket lock and a hardened _graceful_exit() that:

Persisted preferences

Stopped the controller

Destroyed Tk

Called os._exit(0) if needed to prevent lingering python.exe.

A key lesson captured there is:

“Desktop apps need explicit single-instance logic; rely on OS primitives (sockets/mutexes) and have a last-resort exit path when GUI frameworks misbehave.”

V2’s refactor changed the entrypoint and GUI architecture but did not fully carry over this guardrail, which has likely re-opened a path for:

Multiple instances;

Partially-shutdown Tk/threads;

Parent process hanging even after WebUI shutdown.

PR-064 restores that missing safety net.

Implementation Plan
1. Single-Instance Socket Lock (src/utils/single_instance.py + src/main.py)

Goal: On startup, StableNew should:

Try to acquire a localhost socket lock (e.g., fixed port or reserved localhost endpoint).

If the lock is already held:

Log a clear message (and optionally show a small dialog).

Exit immediately with a non-zero status without starting the GUI or WebUI.

Steps:

Create src/utils/single_instance.py:

Provide:

class SingleInstanceLock:
    def __init__(self, name: str = "stablenew_v2", port: int | None = None): ...
    def acquire(self) -> bool: ...
    def release(self) -> None: ...


Implement localhost socket lock similar to the prior V1 pattern (reuse the conceptual approach, not the legacy file path).

In src/main.py:

At the very beginning of the main() function (or equivalent entry):

Instantiate a SingleInstanceLock.

Call lock.acquire():

If False: log and exit with sys.exit(1).

If True: keep the instance around (e.g., app_context.single_instance_lock = lock) so it can be released on shutdown.

Ensure that, in _graceful_exit(), we always release the lock before os._exit(0).

Edge cases:

For headless/journey tests, this instance check still applies, but since they start/stop sequentially, the lock should always be available.

If a prior run leaked and is still holding the lock, this is a correct fail-fast signal that shutdown is still broken.

2. Central _graceful_exit() Helper (src/utils/graceful_exit.py or inside src/main.py)

Goal: Define one canonical function that all exit paths call.

Shape:

def graceful_exit(
    app_controller: AppController | None,
    root: tk.Tk | None,
    single_instance_lock: SingleInstanceLock | None,
    logger: logging.Logger,
    *,
    debug_shutdown: bool = False,
    shutdown_timeout: float = 10.0,
) -> "NoReturn":
    ...


Responsibilities (in order):

Idempotence guard:

Ensure _graceful_exit() only runs once, even if called from multiple paths (X button, Exit command, auto-exit, fatal error).

Simple: internal flag or AppController._shutdown_completed.

Best-effort orderly shutdown:

If app_controller is not None:

Call its shutdown_app() once (or whatever V2 uses as the main shutdown hook).

Avoid joining worker threads from the GUI thread in ways that violate your earlier threading rules (cf. BUG_FIX_GUI_HANG_SECOND_RUN, THREADING_FIX).

If WebUI manager is reachable via the controller, rely on PR-057’s tree-kill logic and do not reimplement it here.

Shutdown inspector (from PR-061):

If debug_shutdown is True or STABLENEW_DEBUG_SHUTDOWN=1:

Call the log_shutdown_state(...) inspector before final exit to capture remaining threads/children.

Tk teardown:

If root is not None:

Ensure root.destroy() is invoked safely (ideally from Tk’s main thread).

If this function is not called from the Tk thread, use root.after(0, lambda: root.destroy()) and wait briefly.

Release the single-instance lock:

If single_instance_lock is acquired, release it.

Watchdog + hard exit:

Optionally sleep a very short grace period (e.g., up to shutdown_timeout, but keep it modest for tests).

Call os._exit(0) unconditionally. The point is: once we are here, we commit to terminating the interpreter even if a rogue thread is still alive.

This matches the spirit of the historical _graceful_exit() which “stops the controller, tears down Tk, and calls os._exit(0) if needed.”

3. Wire All Exit Paths to _graceful_exit()

Files:

src/main.py

src/gui/main_window_v2.py

src/controller/app_controller.py

Steps:

In main.py:

After building the V2 GUI and controller, ensure there is a shared context:

app_controller = ...
root = ...
single_instance_lock = ...

def _on_fatal_error(exc: BaseException) -> "NoReturn":
    logger.exception("Fatal error in StableNew", exc_info=exc)
    graceful_exit(app_controller, root, single_instance_lock, logger, ...)


Wrap the main loop so that any uncaught exceptions route to _on_fatal_error.

In MainWindowV2 (or its controller/wrapper):

Ensure on_app_close() (window X button) calls back into a shutdown hook that eventually calls _graceful_exit(...) once.

Any explicit “Exit” menu/button should do the same.

Auto-exit (from PR-062):

schedule_auto_exit() should, after the delay, call the same close path (on_app_close → _graceful_exit).

No extra code paths should attempt their own partial shutdown.

Guard against double shutdown:

If shutdown_app() is already called, _graceful_exit() should detect this and skip directly to lock release + os._exit(0).

4. Integrate with Journey Test Expectations (tests/journeys/test_shutdown_no_leaks.py)

The existing journey test already:

Starts StableNew via subprocess.Popen([sys.executable, "-m", "src.main"], env=env)

Enables STABLENEW_AUTO_EXIT_SECONDS

Waits up to timeout = auto_exit_seconds + buffer

Kills and fails if the process does not exit

With _graceful_exit() wired as above:

Once auto-exit triggers, the app should:

Run controller + WebUI shutdown

Release the socket lock

Call os._exit(0)

No changes to this test should be necessary beyond:

Ensuring any test-specific environment variables (like STABLENEW_DEBUG_SHUTDOWN) are passed through as needed.

Optionally shortening shutdown_timeout under test to keep runs fast.

Tests

Codex should run:

Target journey test:

pytest tests/journeys/test_shutdown_no_leaks.py::test_shutdown_relaunch_leaves_no_processes -q


Expected after PR-064:

No timeouts waiting for proc.wait(timeout=...).

No remaining StableNew/WebUI processes per the filtered inspector from PR-060.

Smoke manual validation:

Run python -m src.main

Close via:

X button

Any explicit Exit button

Verify in Task Manager that no extra python.exe or SD-WebUI processes remain.

Regression checks:

Run a small subset of GUI + controller tests, especially any that mock or stub shutdown/exit behaviors, to ensure nothing breaks those assumptions.

Definition of Done

PR-064 is complete when:

StableNew enforces single-instance locking from V2 entrypoint.

All GUI/application exit paths route through _graceful_exit():

X button

Exit button/menu

Auto-exit (PR-062)

Fatal error path

_graceful_exit():

Stops controller and WebUI

Tears down Tk

Logs shutdown state (when enabled)

Releases the socket lock

Calls os._exit(0) as a last resort

test_shutdown_relaunch_leaves_no_processes:

No longer times out waiting for the process

No StableNew/WebUI processes remain across multiple cycles

If, after this PR, the test still fails because leaked processes remain, follow-up work should be focused on:

Using the shutdown inspector logs (PR-061) to identify specific threads/processes that are still alive

Creating small, targeted follow-on PRs per culprit (e.g., “stop queue worker X on shutdown”).