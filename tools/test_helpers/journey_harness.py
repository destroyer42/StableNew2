"""Helper utilities for running StableNew journey tests via subprocesses."""

from __future__ import annotations

import os
import subprocess
import sys
from subprocess import CompletedProcess
from typing import Mapping, Optional


def build_env(extra: Optional[Mapping[str, str]] = None) -> dict[str, str]:
    env = dict(os.environ)
    if extra:
        env.update(extra)
    return env


def run_app_once(
    *,
    auto_exit_seconds: float = 3.0,
    timeout_buffer: float = 5.0,
    extra_env: Optional[Mapping[str, str]] = None,
) -> CompletedProcess[str]:
    """Launch `python -m src.main` and await its auto-exit with captured output."""

    env = build_env(extra_env or {})
    env["STABLENEW_AUTO_EXIT_SECONDS"] = str(auto_exit_seconds)
    env["STABLENEW_DEBUG_SHUTDOWN"] = env.get("STABLENEW_DEBUG_SHUTDOWN", "1")

    timeout = auto_exit_seconds + timeout_buffer

    proc = subprocess.Popen(
        [sys.executable, "-m", "src.main"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate(timeout=5)
        raise RuntimeError(
            f"StableNew did not exit within {timeout} seconds (returncode={proc.returncode})"
        )

    return CompletedProcess(
        args=proc.args, returncode=proc.returncode, stdout=stdout, stderr=stderr
    )


def run_journey_mode(
    mode: str,
    *,
    auto_exit_seconds: float = 3.0,
    timeout_buffer: float = 5.0,
    extra_env: Optional[Mapping[str, str]] = None,
) -> CompletedProcess[str]:
    """Run a journey-mode-specific auto-exit invocation (future-proof hook)."""

    env = dict(extra_env or {})
    env["STABLENEW_JOURNEY_MODE"] = mode
    return run_app_once(
        auto_exit_seconds=auto_exit_seconds,
        timeout_buffer=timeout_buffer,
        extra_env=env,
    )
