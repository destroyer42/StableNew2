"""Opt-in local process test: StableNew exits without stray processes.

Set ``STABLENEW_RUN_SHUTDOWN_LEAK_TEST=1`` to run it (scripts/run_shutdown_diag.ps1 does).
It launches the real app several times and inspects host-wide process lists, so it is
never part of required or informational CI. The launched app disables backend autostart. External A1111/ComfyUI
processes are outside this test's ownership and are never inspected or touched.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

from tools.test_helpers import journey_harness
from tools.test_helpers.process_inspection import (
    assert_no_stable_new_processes,
    assert_no_webui_processes,
)


@pytest.mark.slow
@pytest.mark.skipif(
    os.environ.get("STABLENEW_RUN_SHUTDOWN_LEAK_TEST") != "1",
    reason="opt-in local process test: set STABLENEW_RUN_SHUTDOWN_LEAK_TEST=1",
)
@pytest.mark.skipif(
    sys.platform != "win32" and sys.platform != "linux", reason="Platform-specific stability test"
)
def test_shutdown_relaunch_leaves_no_processes() -> None:
    attempts = int(os.environ.get("STABLENEW_SHUTDOWN_LEAK_ATTEMPTS", "3"))
    auto_exit_seconds = float(
        os.environ.get(
            "STABLENEW_AUTO_EXIT_SECONDS", os.environ.get("STABLENEW_SHUTDOWN_LEAK_UPTIME", "3")
        )
    )
    timeout_buffer = float(os.environ.get("STABLENEW_SHUTDOWN_LEAK_TIMEOUT_BUFFER", "5"))

    logs_base = Path("logs") / "journeys" / "shutdown"
    logs_base.mkdir(parents=True, exist_ok=True)
    for _ in range(attempts):
        timestamp = f"{time.strftime('%Y%m%d-%H%M%S')}-{int(time.time() * 1000) % 1000}"
        log_file = logs_base / f"shutdown-journey-{timestamp}.log"
        extra_env = {
            "STABLENEW_DEBUG_SHUTDOWN": "1",
            "STABLENEW_LOG_FILE": str(log_file),
            "STABLENEW_WEBUI_AUTOSTART": "0",
            "STABLENEW_COMFY_AUTOSTART": "0",
            "STABLENEW_WEBUI_BASE_URL": "http://127.0.0.1:9",
            "STABLENEW_COMFY_BASE_URL": "http://127.0.0.1:9",
        }
        if os.environ.get("STABLENEW_FILE_ACCESS_LOG") == "1":
            extra_env["STABLENEW_FILE_ACCESS_LOG"] = "1"

        result = journey_harness.run_app_once(
            auto_exit_seconds=auto_exit_seconds,
            timeout_buffer=timeout_buffer,
            extra_env=extra_env,
        )
        assert result.returncode == 0, f"Process exited with code {result.returncode}"
        assert_no_stable_new_processes()
        assert_no_webui_processes()
