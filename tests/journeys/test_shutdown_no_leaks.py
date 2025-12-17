"""Shutdown journey test ensuring StableNew and WebUI exit without stray processes.

Local entrypoint (Windows PowerShell):
    scripts\run_journey_tests.ps1

CI entrypoint:
    GitHub Actions → Journey Tests (Shutdown / No-Leaks)
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


@pytest.mark.journey
@pytest.mark.slow
@pytest.mark.skipif(
    sys.platform != "win32" and sys.platform != "linux", reason="Platform-specific stability test"
)
@pytest.mark.journey
@pytest.mark.slow
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
