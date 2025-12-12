PR-069 — Log-Driven Shutdown Fixes (V2.5)
Snapshot / Baseline

Snapshot: StableNew-snapshot-20251201-074504.zip

Entrypoint: python -m src.main

Shutdown diagnostics from:

logs/gui-shutdown/gui-shutdown-*.log

logs/journeys/shutdown/shutdown-journey-*.log

logs/file_access/file_access-*.jsonl (when STABLENEW_FILE_ACCESS_LOG=1)

Existing shutdown plumbing:

src/utils/graceful_exit.py

src/controller/app_controller.py (shutdown paths + watchdog)

src/api/webui_process_manager.py (WebUI lifecycle)

src/gui/main_window_v2.py (window close → controller shutdown → Tk teardown)

src/utils/debug_shutdown_inspector.py

Journey tests + helpers:

tests/journeys/test_shutdown_no_leaks.py

tests/controller/test_app_controller_shutdown_v2.py

tests/api/test_webui_process_manager_shutdown_v2.py

tests/gui_v2/test_shutdown_journey_v2.py

tools/test_helpers/journey_harness.py

Guardrail: Do not modify src/main.py, src/gui/main_window_v2.py, src/gui/theme_v2.py, or pipeline executor core in this PR. This PR operates at the controller / process-manager / tests level only.

1. Problem

Even after:

PR-046 / PR-061–063 (shutdown robustness, shutdown inspector, auto-exit mode, meta),

PR-066 (journey test automation),

PR-068 (disk-backed diagnostics logs + file-access tracing),

the shutdown journey still fails intermittently:

tests/journeys/test_shutdown_no_leaks.py sometimes:

Times out waiting for src.main to exit (subprocess.TimeoutExpired), or

Reports lingering StableNew or WebUI processes.

At this point, we have:

Rich logs (threads + child processes) at shutdown,

A watchdog in AppController.shutdown_app that can force a hard exit,

Tk’s window-close path wired to graceful_exit.

But we haven’t run a log-driven tightening pass to:

Identify which specific threads or child processes remain alive, and

Add targeted shutdown logic for those culprits.

This PR is exactly that pass.

2. Goals

Use the new shutdown logs to identify the concrete hang pattern(s):

Which threads still exist after shutdown (by name)?

Which child processes (esp. WebUI) survive beyond shutdown?

Which shutdown phase is the last one logged by AppController before nothing more appears?

Implement targeted fixes for the discovered patterns, focusing on:

Ensuring all non-daemon worker threads that can survive beyond GUI close are stopped/joined.

Ensuring WebUI is fully shut down and no new WebUI instance is started as part of shutdown.

Ensuring any background “watchers” (status polling, healthcheck loops, etc.) are stopped.

Harden the shutdown journey tests so they:

Cover the specific failure mode(s) seen in the logs.

Fail deterministically with useful assertions instead of raw TimeoutExpired.

Preserve existing behavior for normal users:

No new popups, no behavior changes on regular closes beyond “it actually exits.”

3. Scope & Risk

Risk tier: Medium

We’re touching shutdown paths, which are sensitive, but staying out of main.py and Tk wiring.

Allowed files (proposed):

src/controller/app_controller.py

src/api/webui_process_manager.py

src/utils/debug_shutdown_inspector.py (small enhancements only)

tools/test_helpers/journey_harness.py

tests/journeys/test_shutdown_no_leaks.py

tests/controller/test_app_controller_shutdown_v2.py

tests/api/test_webui_process_manager_shutdown_v2.py

tests/gui_v2/test_shutdown_journey_v2.py

Forbidden in this PR:

src/main.py

src/gui/main_window_v2.py

src/gui/theme_v2.py

Pipeline executor / queue / learning core internals.

4. Log-Driven Diagnosis Plan (what Codex must do first)

Before changing behavior, Codex must inspect real logs from failing runs:

Collect at least two failing journey runs for tests/journeys/test_shutdown_no_leaks.py with:

STABLENEW_DEBUG_SHUTDOWN=1

STABLENEW_FILE_ACCESS_LOG=1

The environment / harness already wired by PR-068.

For each failing run:

Open the corresponding shutdown log:

From logs/journeys/shutdown/shutdown-journey-*.log (journey-specific)
or logs/gui-shutdown/gui-shutdown-*.log.

Look at:

The last few lines from:

graceful_exit ([graceful_exit] Initiating (...))

AppController.shutdown_app ([controller] shutdown_app called (...))

Any WebUI shutdown result: ... lines.

Any “Shutdown watchdog triggered” messages from _shutdown_watchdog.

The thread list from log_shutdown_state(...) (thread names, daemon flags).

Child process lines from debug_shutdown_inspector (WebUI PID, command line).

Open the matching file-access log (logs/file_access/*.jsonl) and:

Check what files were accessed near the end of the run (optional, but may reveal e.g. stuck I/O).

Categorize each failing run into one or more buckets:

Category A – WebUI child still running:

Logs show WebUI process still alive after AppController._shutdown_webui returns.

Category B – Controller shutdown not completing:

_shutdown_watchdog logs completed=False.

The last log is somewhere before self._shutdown_completed = True.

Category C – Non-daemon thread(s) still alive:

log_shutdown_state lists thread(s) with daemon=False that clearly belong to StableNew.

Category D – Tk / GUI teardown path not reached:

Shutdown logs show AppController.shutdown_app running, but Tk callbacks appear to be blocked or not invoked in auto-exit scenarios.

The concrete fixes below assume you’ll find at least one of A/B/C. If not, document why in comments and keep the PR minimal.

5. Implementation (Targeted Fixes)

Below are concrete actions, organized by category. Apply whichever categories the real logs actually reveal. If multiple categories are present, apply all relevant ones in a single coordinated change set.

5.1 Category A — WebUI child still running after shutdown

Files:

src/api/webui_process_manager.py

src/controller/app_controller.py

tests/api/test_webui_process_manager_shutdown_v2.py

tests/controller/test_app_controller_shutdown_v2.py

Fixes:

Harden WebUIProcessManager.stop_webui for stubborn processes:

After the existing grace_seconds loop and _kill_process_tree(pid) call, add a final check:

If self.is_running() is still True, log an ERROR with PID & command.

Then call self._kill_process_tree(pid) again as a best-effort final nuke.

Guarantee _finalize_process(...) is invoked exactly once, and that _process is set to None at the end.

Expose a “blocking shutdown” helper (if not already implied):

Add a small helper like def shutdown_blocking(self, grace_seconds: float = 10.0) -> bool that:

Calls stop_webui(grace_seconds) and then rechecks is_running() with a short spin loop.

Use that helper in controller shutdown (below) only if logs show we’re leaving processes behind.

In AppController._shutdown_webui:

After stop_fn() returns and the “WebUI shutdown result” log is written, explicitly re-check manager.is_running().

If still running:

Log an error: "WebUI still running after stop_webui; forcing process tree kill."

Call manager._kill_process_tree(manager.pid) (via a safe wrapper; do not access private method directly if you can avoid it).

Ensure the HTTP-level WebUI connection is not re-triggered during shutdown (no late ensure_running calls).

Tests:

In tests/api/test_webui_process_manager_shutdown_v2.py, add a test where:

The fake process never returns from poll() as “not running” quickly.

Assert that stop_webui eventually calls kill / tree kill and that _process is cleared.

In tests/controller/test_app_controller_shutdown_v2.py, add a test using a fake WebUIProcessManager that:

Reports running → then stuck → then stopped.

Assert _shutdown_webui calls its stop method and logs appropriately without hanging.

5.2 Category B — AppController.shutdown_app not completing

Files:

src/controller/app_controller.py

tests/controller/test_app_controller_shutdown_v2.py

Fixes:

Phase logging: reinforce the logs inside shutdown_app so we can see progress:

Before each major phase, log:

"[controller] shutdown_app: phase=cancel_active_jobs"

"[controller] shutdown_app: phase=stop_background_work"

"[controller] shutdown_app: phase=shutdown_learning_hooks"

"[controller] shutdown_app: phase=shutdown_webui"

"[controller] shutdown_app: phase=shutdown_job_service"

"[controller] shutdown_app: phase=join_worker_thread"

This is cheap and should already be present in some form; unify the pattern so the logs are easy to scan.

Ensure _shutdown_watchdog can actually hard-exit during tests if requested:

_shutdown_watchdog already:

Sleeps for STABLENEW_SHUTDOWN_WATCHDOG_DELAY (default 8s).

Logs an error and optionally calls os._exit(1) if STABLENEW_HARD_EXIT_ON_SHUTDOWN_HANG=1.

For journey tests only, we will rely on this behavior to avoid TimeoutExpired:

See test wiring in section 5.4.

Defensive timeout on _join_worker_thread:

Confirm _join_worker_thread uses a finite timeout (currently 2s); keep it that way.

After a failed join (thread still alive), log a warning and do not block further; let the watchdog and graceful_exit inspect and force exit if necessary.

Tests:

Extend tests/controller/test_app_controller_shutdown_v2.py with a test that simulates:

A “hung” worker thread that never terminates.

Verify that:

shutdown_app does not block indefinitely.

_shutdown_watchdog would log the hang (you can simulate by calling it directly with STABLENEW_HARD_EXIT_ON_SHUTDOWN_HANG disabled).

5.3 Category C — Non-daemon threads or background workers surviving

Files:

src/controller/app_controller.py

(Optionally) any small helper modules that own background threads (e.g. job service runners).

src/utils/debug_shutdown_inspector.py

tests/controller/test_app_controller_shutdown_v2.py

Fixes:

From the logs, identify which thread names are still alive at shutdown time (e.g. "WebUIHealthCheckThread", "JobWorkerThread", "LearningPoller").

For each such thread type:

Find where it is created (e.g. inside job service, learning controller, WebUI healthcheck).

Ensure:

It’s either marked as daemon=True, or

It has a clear stop() / shutdown() path that is invoked from:

AppController.stop_all_background_work(), or

The corresponding _shutdown_* helper (e.g. _shutdown_job_service).

Update debug_shutdown_inspector.log_shutdown_state to make the output easier to correlate:

Include whether the thread is daemon, and maybe the module (thread.__class__.__module__) if helpful.

(Keep it lightweight; no new dependencies.)

Tests:

Add a controller-level test that:

Installs a fake non-daemon background thread, registers it with the controller, and ensures:

After shutdown_app, the thread either becomes non-alive or is at least logged as a shutdown failure (but without blocking).

5.4 Test Harness & Journey Wiring

Files:

tools/test_helpers/journey_harness.py

tests/journeys/test_shutdown_no_leaks.py

Fixes:

Fix the sys NameError and markers (match your local version):

Ensure tests/journeys/test_shutdown_no_leaks.py imports sys at top:

import os
import sys


Keep the marks:

@pytest.mark.journey
@pytest.mark.slow
@pytest.mark.skipif(sys.platform != "win32" and sys.platform != "linux", reason="Platform-specific stability test")


Wire shutdown diagnostics consistently (building on PR-068):

In journey_harness.run_app_once, make sure extra_env is merged and includes:

STABLENEW_DEBUG_SHUTDOWN=1

STABLENEW_SHUTDOWN_WATCHDOG_DELAY set to a reasonable small value for tests (e.g. 8).

Do not set STABLENEW_HARD_EXIT_ON_SHUTDOWN_HANG by default in this PR; keep hard exits opt-in so we still see hangs in CI, but note in comments that setting it to 1 is the “ultimate nuke” option if needed.

Journey test assertions (once fixes are in place):

test_shutdown_relaunch_leaves_no_processes should assert:

Child process exits within the timeout (no TimeoutExpired).

assert_no_stable_new_processes() passes.

assert_no_webui_processes() passes.

Optionally, if diagnostics are available:

On failure, print a hint that points to logs/journeys/shutdown and logs/file_access for triage.

6. Acceptance Criteria

For this PR to be considered complete:

Running:

# From repo root
pytest tests/journeys/test_shutdown_no_leaks.py -q


under the same conditions that previously failed must now:

Complete without TimeoutExpired or hanging.

Leave no lingering StableNew or WebUI python processes.

Shutdown logs from a few sample runs (success + failure simulations) show:

graceful_exit and AppController.shutdown_app phases completing.

log_shutdown_state confirming no unexpected non-daemon StableNew threads remain.

No leftover WebUI child process after _shutdown_webui.

All updated unit tests pass:

tests/api/test_webui_process_manager_shutdown_v2.py

tests/controller/test_app_controller_shutdown_v2.py

tests/gui_v2/test_shutdown_journey_v2.py

tests/journeys/test_shutdown_no_leaks.py

No behavior regressions:

Manual run of python -m src.main:

Open GUI, close via X → process exits.

Run, let auto-exit (via STABLENEW_AUTO_EXIT_SECONDS) → process exits.