PR-062 — Headless Auto-Exit Mode for Clean Shutdown Journey Tests (V2-P1)
Add a deterministic, testable shutdown path so journey tests exercise a REAL GUI exit instead of killing the process.
Summary

The journey test currently uses proc.terminate(), which bypasses the entire shutdown path (on_app_close(), controller shutdown, WebUIProcessManager cleanup, etc.). To test proper shutdown, we need a way to trigger the real GUI exit while running in a headless subprocess.

This PR introduces a --auto-exit / env-based timed shutdown mode that:

Launches the GUI normally

Waits N seconds

Calls the same close path as clicking the X button

Allows journey tests to evaluate true shutdown correctness

Goals

Add STABLENEW_AUTO_EXIT_SECONDS (or CLI arg) to trigger scheduled app shutdown.

Implement schedule_auto_exit() inside MainWindowV2.

Modify journey tests to use this instead of terminate().

Allowed Files

src/main.py

src/gui/main_window_v2.py

tests/journeys/test_shutdown_no_leaks.py

Forbidden Files

Pipeline executor

WebUIProcessManager (covered by PR-057)

Implementation Details
1. Add auto-exit env/CLI flag to main.py

Parse early in main:

auto_exit_after = float(os.environ.get("STABLENEW_AUTO_EXIT_SECONDS", "0"))


Pass to app builder:

gui = build_v2_app(...)
if auto_exit_after > 0:
    gui.schedule_auto_exit(auto_exit_after)

2. Implement schedule_auto_exit() in MainWindowV2
def schedule_auto_exit(self, seconds: float) -> None:
    ms = int(seconds * 1000)
    self.root.after(ms, self.on_app_close)


This triggers the exact same shutdown sequence as the user clicking X.

3. Update journey test to use clean shutdown

Replace:

proc.terminate()


With:

env = os.environ.copy()
env["STABLENEW_AUTO_EXIT_SECONDS"] = uptime_seconds

proc = subprocess.Popen([sys.executable, "-m", "src.main"], env=env)
proc.wait(timeout=timeout)
assert proc.returncode == 0
assert_no_stable_new_processes()


This now tests the real shutdown path.

Tests

Update test_shutdown_no_leaks.py:

Use auto-exit mode

Assert:

Process exits cleanly with returncode 0

No lingering StableNew/WebUI processes remain

Process inspector uses PR-060 filtering

Definition of Done

Journey test uses real shutdown path.

Shutdown behaves identically to user-initiated close.

No process leaks after clean auto-exit cycles.