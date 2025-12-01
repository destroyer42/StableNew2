PR-061 — Deep Shutdown Instrumentation (Threads + Child Processes) (V2-P1)
Add shutdown introspection so we can see exactly which threads/processes keep StableNew alive.
Summary

Even with improved shutdown logic, we still cannot see why the main Python interpreter remains alive after GUI exit. This PR adds a “shutdown inspector” that logs:

All alive threads

Whether threads are daemon/non-daemon

All child processes (via psutil, where available)

Any unhandled exceptions during shutdown

This gives Codex (and you) complete post-shutdown visibility.

Goals

Log all thread activity at shutdown exit.

Log child processes still attached to StableNew.

Optional config flag lets us enable/disable this instrumentation at runtime.

Zero effect on production behavior unless enabled.

Allowed Files

src/controller/app_controller.py

src/utils/debug_shutdown_inspector.py (NEW)

src/config/app_config.py (optional config flag)

Forbidden Files

GUI modules

Pipeline executor

WebUIProcessManager (already handled in PR-057)

Implementation Details
1. Add new module: debug_shutdown_inspector.py
def log_shutdown_state(logger, label: str) -> None:
    logger.info("=== Shutdown Inspector (%s) ===", label)

    # Thread enumeration
    for t in threading.enumerate():
        logger.info(
            "Thread: name=%s daemon=%s alive=%s",
            t.name, t.daemon, t.is_alive()
        )

    # Child process enumeration (if psutil available)
    try:
        import psutil, os
        p = psutil.Process(os.getpid())
        for child in p.children(recursive=True):
            logger.info(
                "Child: pid=%s name=%s cmdline=%s",
                child.pid, child.name(), child.cmdline()
            )
    except Exception:
        logger.exception("Failed to capture process state")

2. Integrate into AppController.shutdown_app()

Near the end of the shutdown_app() method:

if config.debug_shutdown_inspector_enabled:
    log_shutdown_state(logger, "post-shutdown")
self._shutdown_completed = True

3. Add toggle

In app_config:

debug_shutdown_inspector_enabled: bool = False


Also support env var:

STABLENEW_DEBUG_SHUTDOWN=1

Tests

Add tests/controller/test_shutdown_inspector_v2.py

Mocks 2–3 fake threads.

Runs log_shutdown_state(...).

Asserts log entries appear.

No GUI tests needed.

Definition of Done

Logs show explicit list of all threads + child processes after shutdown.

The inspector helps pinpoint which threads or children keep the process alive.

No runtime change when disabled.