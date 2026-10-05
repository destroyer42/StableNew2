"""Resolve the per-user directory that owns the saved Global Positive/Negative prompt text."""

from __future__ import annotations

import os
import platform
from collections.abc import Mapping
from pathlib import Path

GLOBAL_PROMPT_DIR_ENV = "STABLENEW_GLOBAL_PROMPT_DIR"
GLOBAL_POSITIVE_FILENAME = "global_positive.txt"
GLOBAL_NEGATIVE_FILENAME = "global_negative.txt"


def resolve_global_prompt_dir(
    global_prompt_dir: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    system_name: str | None = None,
    home_dir: str | Path | None = None,
) -> Path:
    """Return the canonical Global Prompt directory without creating it.

    Explicit dependency injection wins, followed by ``STABLENEW_GLOBAL_PROMPT_DIR``.
    The remaining locations follow the platform's normal per-user data convention
    (``%LOCALAPPDATA%\\StableNew\\GlobalPrompts`` on Windows) and deliberately never
    consult a repository-relative ``presets`` directory.
    """

    if global_prompt_dir is not None:
        return Path(global_prompt_dir)

    environment = os.environ if environ is None else environ
    configured_dir = environment.get(GLOBAL_PROMPT_DIR_ENV)
    if configured_dir:
        return Path(configured_dir)

    resolved_system = system_name or platform.system()
    if resolved_system == "Windows":
        local_app_data = environment.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "StableNew" / "GlobalPrompts"
        # LOCALAPPDATA is present on supported Windows installations. Keep a
        # deterministic user-scoped fallback for constrained test/process hosts.
        home = Path(home_dir) if home_dir is not None else Path.home()
        return home / "AppData" / "Local" / "StableNew" / "GlobalPrompts"

    data_home = environment.get("XDG_DATA_HOME")
    if data_home:
        return Path(data_home) / "StableNew" / "GlobalPrompts"
    home = Path(home_dir) if home_dir is not None else Path.home()
    return home / ".local" / "share" / "StableNew" / "GlobalPrompts"


__all__ = [
    "GLOBAL_NEGATIVE_FILENAME",
    "GLOBAL_POSITIVE_FILENAME",
    "GLOBAL_PROMPT_DIR_ENV",
    "resolve_global_prompt_dir",
]
