"""Execution modes, CLI validation and the refusal to run physical work from CI or pytest."""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping

SIMULATED = "simulated"
READINESS = "readiness"
PHYSICAL = "physical"
MODES = (SIMULATED, READINESS, PHYSICAL)
DRIVERS = ("tk", "windows")
LAYOUTS = ("maximized", "normal", "minimum")
JOURNEY_CHOICES = ("image", "video", "learning", "all")

_CI_MARKERS = ("CI", "GITHUB_ACTIONS", "TF_BUILD", "JENKINS_URL", "BUILDKITE")


class ModeRefusal(RuntimeError):
    """The requested combination is not allowed; the message is shown to the operator."""


def running_in_ci(env: Mapping[str, str] | None = None) -> bool:
    env = os.environ if env is None else env
    return any(
        str(env.get(key, "")).strip().lower() not in {"", "0", "false"} for key in _CI_MARKERS
    )


def running_under_pytest(
    env: Mapping[str, str] | None = None, modules: Mapping | None = None
) -> bool:
    env = os.environ if env is None else env
    modules = sys.modules if modules is None else modules
    return bool(env.get("PYTEST_CURRENT_TEST")) or "pytest" in modules


def validate_combination(
    *,
    mode: str,
    driver: str,
    plan: object | None,
    env: Mapping[str, str] | None = None,
    layout: str = "maximized",
) -> None:
    """Refuse invalid or unsafe combinations before anything starts."""

    if layout not in LAYOUTS:
        raise ModeRefusal(f"unknown layout {layout!r}; choose one of {LAYOUTS}")
    if layout != "maximized" and driver != "windows":
        raise ModeRefusal("--layout normal|minimum needs --desktop-driver windows (a real window)")
    if mode not in MODES:
        raise ModeRefusal(f"unknown mode {mode!r}; choose one of {MODES}")
    if driver not in DRIVERS:
        raise ModeRefusal(f"unknown desktop driver {driver!r}; choose one of {DRIVERS}")
    if mode in (READINESS, PHYSICAL) and plan is None:
        raise ModeRefusal(f"--mode {mode} requires --plan <frozen plan file>")
    if mode == SIMULATED and plan is not None:
        raise ModeRefusal("--plan is only valid with --mode readiness or --mode physical")
    if driver == "windows" and running_in_ci(env):
        raise ModeRefusal("the Windows input driver is never used in CI")
    if mode == PHYSICAL:
        if running_in_ci(env):
            raise ModeRefusal("physical execution is refused in CI")
        if running_under_pytest(env):
            raise ModeRefusal("physical execution is refused under pytest")
        if driver != "windows":
            raise ModeRefusal("physical execution runs through the visible Windows desktop driver")
        if sys.platform != "win32":
            raise ModeRefusal("physical execution requires a Windows desktop")
