PR-068 — Shutdown Diagnostics Log + File Access Trace (V2.5)

Snapshot baseline

Repo root: C:\Users\rob\projects\StableNew

Snapshot: snapshots/StableNew-snapshot-20251201-074504.zip

This PR is consistent with the existing V2 wiring / documentation strategy and Phase 1 stabilization goals (stable GUI V2 wiring, deterministic logging & diagnostics).

1. Problem

The shutdown inspector (PR-061) logs useful state (log_shutdown_state) but only to the root logger’s stream handler, which is:

Routed into the GUI terminal window, and

Lost or inaccessible when the GUI freezes or pytest kills the process.

We previously added a V2.5 file access logger (src/utils/file_access_log_v2_5_2025_11_26.py) and optional hooks in src/main.py, but they’re env-flag only and not tied to a standard diagnostic workflow.

When tests/journeys/test_shutdown_no_leaks.py fails, we don’t get a durable view of:

Which threads and child processes were still alive.

What files the app had been touching leading up to the hang.

We need a “flip a switch, then inspect disk logs” story instead of eyeballing a frozen console.

2. Goals

Persist shutdown diagnostics to disk by default in debug/diagnostic runs:

Introduce a well-known log location for shutdown diagnostics, e.g. logs/gui-shutdown/gui-shutdown-YYYYMMDD-HHMMSS.log.

Ensure log_shutdown_state(...) output and all relevant shutdown logs end up in that file.

Make file-access tracing easy to turn on for investigative runs:

Wire the existing FileAccessLogger into a repeatable “diagnostic mode” using env vars.

Ensure each diagnostic run gets its own JSONL file, e.g. logs/file_access/file_access-<timestamp>.jsonl.

Integrate diagnostics with the shutdown journey test:

When tests/journeys/test_shutdown_no_leaks.py runs, ensure:

Shutdown inspector is enabled.

A per-run shutdown log file is created.

File-access logging is optionally enabled for deep dives.

Zero behavior change for “normal” users:

Logging to disk only kicks in under explicit env flags or test harness configuration.

No changes to pipeline behavior, WebUI startup timing, or GUI layout.

3. Non-Goals

No attempt to fix the underlying shutdown hang in this PR.

No changes to WebUI process management semantics (start/shutdown) beyond extra logging.

No changes to learning system, queue/cluster, or pipeline runtime behavior.

No restructuring of the logger module beyond what’s needed to add a file handler & paths.

4. Scope & Risk

Risk tier: Medium

Touches src/main.py (entrypoint) and test harness, but only in a logging/diagnostic capacity.

No core pipeline runner or executor changes.

Allowed files (proposed):

src/main.py

src/utils/logger.py (optional, small enhancement only)

src/utils/file_access_log_v2_5_2025_11_26.py (optional metadata enhancements)

tools/test_helpers/journey_harness.py

tests/journeys/test_shutdown_no_leaks.py

scripts/run_shutdown_diag.ps1 (new helper script)

docs/pr_templates/ (optional: short README snippet or diagnostics note, if desired)

Forbidden (unchanged):

src/pipeline/executor.py

src/gui/main_window_v2.py

src/gui/theme_v2.py

Pipeline runner core, healthcheck core, learning core.

5. Design
5.1 Log file support via setup_logging

We already have setup_logging(log_level: str, log_file: Optional[str] = None) in src/utils/logger.py. The root logger attaches a FileHandler when log_file is passed.

Design choice: Don’t invent a new logging mechanism; just start using log_file from main when a diagnostics env var is set.

Introduce a new env convention:

STABLENEW_LOG_FILE — absolute or relative path for the main log file.

If unset but STABLENEW_DEBUG_SHUTDOWN=1, derive a default:

logs/gui-shutdown/gui-shutdown-<timestamp>.log

Centralize creation of the parent directory (logs/gui-shutdown) in src/main.py right before setup_logging.

5.2 Standard “diagnostic mode” env contract

Re-use existing flags & add one more:

Already present:

STABLENEW_DEBUG_SHUTDOWN → is_debug_shutdown_inspector_enabled() in src/config/app_config.py.

STABLENEW_FILE_ACCESS_LOG → optional hooks in main() to install file-access tracking (FileAccessLogger).

New or clarified:

STABLENEW_LOG_FILE (optional):

When set, setup_logging("INFO", log_file=...) uses this path.

When not set but STABLENEW_DEBUG_SHUTDOWN=1, main() will auto-generate a path.

Journeys will set:

STABLENEW_DEBUG_SHUTDOWN=1

STABLENEW_LOG_FILE=logs/journeys/shutdown/shutdown-<timestamp>.log

Optionally: STABLENEW_FILE_ACCESS_LOG=1 to turn on the JSONL file access trace for that run.

5.3 File-access logging

src/utils/file_access_log_v2_5_2025_11_26.py already gives us:

FileAccessLogger(...)

_DEFAULT_LOG_PATH = Path("logs/file_access_v2_5.log")

log_file_access(path, reason, stack=None) convenience function.

And src/main.py already has:

Import of FileAccessLogger.

_install_file_access_hooks(...) that wraps:

builtins.open

Path.open

importlib.import_module

The missing pieces are:

Per-run file naming for diagnostics.

A consistent way to enable it automatically for journey tests.

Design:

Keep existing behavior: when STABLENEW_FILE_ACCESS_LOG=1, main() creates:

logs/file_access/file_access-<int(time.time())>.jsonl

For the shutdown journey test, we’ll explicitly set STABLENEW_FILE_ACCESS_LOG=1 and let main use that path (or, if needed, we can add STABLENEW_FILE_ACCESS_LOG_PATH in a future PR; not strictly required here).

5.4 Journey harness integration

tools/test_helpers/journey_harness.py currently:

Builds an environment via build_env(extra_env) and run_app_once(...) (subprocess, -m src.main).

We will extend this to accept an optional diagnostic flag, or simply pass extra_env from tests.

Design choice:

Keep journey_harness generic.

For this PR, wire diagnostics in test_shutdown_no_leaks.py by passing extra_env.

6. Step-by-Step Implementation
Step 1 — Add file-based logging to main()

File: src/main.py

At the top of main(), change:

def main() -> None:
    """Main function"""
    setup_logging("INFO")


to:

def main() -> None:
    """Main function"""

    # Determine log file (optional, driven by env)
    log_file = os.environ.get("STABLENEW_LOG_FILE")
    if log_file is None and os.environ.get("STABLENEW_DEBUG_SHUTDOWN") == "1":
        logs_dir = Path("logs") / "gui-shutdown"
        logs_dir.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        log_file = str(logs_dir / f"gui-shutdown-{timestamp}.log")

    # If log_file is still None, logging remains console-only
    setup_logging("INFO", log_file=log_file)


Note: this assumes setup_logging is already imported from src.utils.logger. If not, add the import instead of inlining.

Ensure no other callers of setup_logging are modified in this PR (to keep scope tight).

Step 2 — Confirm/clarify file-access diagnostics hook in main()

File: src/main.py (already has hooks)

Locate the existing block:

file_access_logger = None
if os.environ.get("STABLENEW_FILE_ACCESS_LOG") == "1":
    logs_dir = Path("logs") / "file_access"
    log_path = logs_dir / f"file_access-{int(time.time())}.jsonl"
    file_access_logger = FileAccessLogger(log_path)
    _install_file_access_hooks(file_access_logger)


Ensure:

logs_dir.mkdir(parents=True, exist_ok=True) is called before constructing log_path.

A short comment is present explaining that this is diagnostic-only and can be expensive, so it should be toggled via env.

Optional small tweak (safe):

If not already present, add a logger info line:

logging.getLogger(__name__).info("File access logging enabled at %s", log_path)


so we can see the JSONL file path in the main log.

Step 3 — Wire diagnostics into the shutdown journey test

File: tests/journeys/test_shutdown_no_leaks.py

At the top, import what we need:

import time
from pathlib import Path


Inside the test (current pattern is result = journey_harness.run_app_once(...)), change to:

attempts = int(os.environ.get("STABLENEW_SHUTDOWN_LEAK_ATTEMPTS", "3"))
auto_exit_seconds = float(
    os.environ.get("STABLENEW_AUTO_EXIT_SECONDS", os.environ.get("STABLENEW_SHUTDOWN_LEAK_UPTIME", "3"))
)
timeout_buffer = float(os.environ.get("STABLENEW_SHUTDOWN_LEAK_TIMEOUT_BUFFER", "5"))

for _ in range(attempts):
    # Per-attempt diagnostic log file
    logs_dir = Path("logs") / "journeys" / "shutdown"
    logs_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    log_file = logs_dir / f"shutdown-journey-{timestamp}.log"

    extra_env = {
        "STABLENEW_DEBUG_SHUTDOWN": "1",
        "STABLENEW_LOG_FILE": str(log_file),
        # Optional: turn on file-access tracing if needed
        "STABLENEW_FILE_ACCESS_LOG": os.environ.get("STABLENEW_FILE_ACCESS_LOG", "0"),
    }

    result = journey_harness.run_app_once(
        auto_exit_seconds=auto_exit_seconds,
        timeout_buffer=timeout_buffer,
        extra_env=extra_env,
    )
    assert result.returncode == 0, f"Process exited with code {result.returncode}"
    assert_no_stable_new_processes()
    assert_no_webui_processes()


This way, every failure of the shutdown journey test leaves behind:

A detailed shutdown log at logs/journeys/shutdown/shutdown-journey-<timestamp>.log.

Optionally, a file-access trace (if STABLENEW_FILE_ACCESS_LOG=1 on the outer environment).

Step 4 — Ensure journey_harness respects extra_env

File: tools/test_helpers/journey_harness.py

Confirm that run_app_once already accepts extra_env and merges it into env = build_env(extra_env) before subprocess.run / Popen. If not, adjust run_app_once to:

def run_app_once(
    *,
    auto_exit_seconds: float = 3.0,
    timeout_buffer: float = 5.0,
    extra_env: Optional[Mapping[str, str]] = None,
) -> CompletedProcess[str]:
    env = build_env(extra_env)
    env["STABLENEW_AUTO_EXIT_SECONDS"] = str(auto_exit_seconds)
    timeout = auto_exit_seconds + timeout_buffer
    return subprocess.run(
        [sys.executable, "-m", "src.main"],
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
    )


Do not add new behavior beyond the env wiring; keep it purely a helper.

Step 5 — Add a simple local diagnostics script (optional but recommended)

File: scripts/run_shutdown_diag.ps1 (new)

A minimal PowerShell helper for you (and future contributors) to gather logs outside pytest:

param(
    [int]$Attempts = 3,
    [int]$UptimeSeconds = 5,
    [int]$TimeoutBufferSeconds = 5
)

$env:STABLENEW_DEBUG_SHUTDOWN = "1"
$env:STABLENEW_FILE_ACCESS_LOG = "1"
$env:STABLENEW_SHUTDOWN_LEAK_ATTEMPTS = "$Attempts"
$env:STABLENEW_SHUTDOWN_LEAK_UPTIME = "$UptimeSeconds"
$env:STABLENEW_SHUTDOWN_LEAK_TIMEOUT_BUFFER = "$TimeoutBufferSeconds"

pytest tests/journeys/test_shutdown_no_leaks.py -q


This simply wraps the test while turning all the diagnostics knobs on.

7. Tests

New / updated tests to run:

Unit / fast tests

python -m pytest tests/utils/test_logger.py -q (if present)

python -m pytest tools/test_helpers/test_journey_harness.py -q (if present)

Journey tests

Default journey (no extra env):

python -m pytest tests/journeys/test_shutdown_no_leaks.py -q


Expect:

Test passes (or fails for the original bug), and

When diagnostics env vars are set, log files created under logs/journeys/shutdown/.

With full diagnostics (from PowerShell):

scripts\run_shutdown_diag.ps1 -Attempts 1 -UptimeSeconds 3 -TimeoutBufferSeconds 5


Then examine:

logs/journeys/shutdown/shutdown-journey-*.log

logs/file_access/file_access-*.jsonl (if STABLENEW_FILE_ACCESS_LOG was enabled)

8. Validation Checklist

 App still starts normally via python -m src.main with no env flags set.

 No new log files created in vanilla runs (no env flags).

 With STABLENEW_DEBUG_SHUTDOWN=1 and no STABLENEW_LOG_FILE env var:

A log file is created under logs/gui-shutdown/.

Shutdown inspector entries (=== Shutdown inspector (...) ===, thread & process info) appear in the file.

 With STABLENEW_FILE_ACCESS_LOG=1, a JSONL file is created under logs/file_access/ and populated with entries.

 tests/journeys/test_shutdown_no_leaks.py:

Creates a per-attempt shutdown log under logs/journeys/shutdown/.

Respects STABLENEW_FILE_ACCESS_LOG if set externally.

 No changes to pipeline behavior, GUI layout, or WebUI healthcheck flow.

 CI passes (or any remaining journey failures are now backed by disk logs that you can inspect).