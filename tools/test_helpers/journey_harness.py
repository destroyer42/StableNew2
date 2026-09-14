"""Helper utilities for running StableNew journey tests via subprocesses."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping
from subprocess import CompletedProcess
from uuid import uuid4

from tools.test_helpers.process_inspection import (
    STABLENEW_OWNER_ENV,
    STABLENEW_RUN_ENV,
    register_test_owned_process,
)


def build_env(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ)
    if extra:
        env.update(extra)
    return env


def run_app_once(
    *,
    auto_exit_seconds: float = 3.0,
    timeout_buffer: float = 5.0,
    extra_env: Mapping[str, str] | None = None,
) -> CompletedProcess[str]:
    """Launch `python -m src.main` and await its auto-exit with captured output."""

    env = build_env(extra_env or {})
    env["STABLENEW_AUTO_EXIT_SECONDS"] = str(auto_exit_seconds)
    env["STABLENEW_DEBUG_SHUTDOWN"] = env.get("STABLENEW_DEBUG_SHUTDOWN", "1")
    env[STABLENEW_OWNER_ENV] = str(os.getpid())
    env[STABLENEW_RUN_ENV] = str(uuid4())

    timeout = auto_exit_seconds + timeout_buffer

    proc = subprocess.Popen(
        [sys.executable, "-m", "src.main"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    register_test_owned_process(proc)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as err:
        proc.kill()
        proc.wait(timeout=5)
        raise RuntimeError(
            f"StableNew did not exit within {timeout} seconds (returncode={proc.returncode})"
        ) from err

    return CompletedProcess(
        args=proc.args, returncode=proc.returncode, stdout=stdout, stderr=stderr
    )


def run_journey_mode(
    mode: str,
    *,
    auto_exit_seconds: float = 3.0,
    timeout_buffer: float = 5.0,
    extra_env: Mapping[str, str] | None = None,
) -> CompletedProcess[str]:
    """Run a journey-mode-specific auto-exit invocation (future-proof hook)."""

    env = dict(extra_env or {})
    env["STABLENEW_JOURNEY_MODE"] = mode
    return run_app_once(
        auto_exit_seconds=auto_exit_seconds,
        timeout_buffer=timeout_buffer,
        extra_env=env,
    )
