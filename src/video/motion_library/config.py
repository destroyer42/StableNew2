"""Where the operator's Motion Library lives (PR-VID-MOTION-LIB-353).

The library root is an explicit choice, remembered in one small per-user pointer file next to the other
per-user StableNew data (``%LOCALAPPDATA%\\StableNew\\motion_library.json``), never in the repository and
never in ``presets/``.  Nothing is created until the operator picks a folder; the suggested default is
only a suggestion shown to the operator.
"""

from __future__ import annotations

import json
import os
import platform
from collections.abc import Mapping
from pathlib import Path

from src.utils.atomic_io import atomic_write_json
from src.video.motion_library.store import validate_library_root

CONFIG_NAME = "motion_library.json"
ROOT_KEY = "library_root"
ENV_OVERRIDE = "STABLENEW_MOTION_LIBRARY_DIR"


def _user_data_dir(
    environ: Mapping[str, str] | None, system_name: str | None, home_dir: str | Path | None
) -> Path:
    environment = os.environ if environ is None else environ
    system = system_name or platform.system()
    home = Path(home_dir) if home_dir is not None else Path.home()
    if system == "Windows":
        local = environment.get("LOCALAPPDATA")
        return (Path(local) if local else home / "AppData" / "Local") / "StableNew"
    data_home = environment.get("XDG_DATA_HOME")
    return (Path(data_home) if data_home else home / ".local" / "share") / "StableNew"


def config_path(
    *,
    environ: Mapping[str, str] | None = None,
    system_name: str | None = None,
    home_dir: str | Path | None = None,
) -> Path:
    return _user_data_dir(environ, system_name, home_dir) / CONFIG_NAME


def suggested_library_root(
    *,
    environ: Mapping[str, str] | None = None,
    system_name: str | None = None,
    home_dir: str | Path | None = None,
) -> Path:
    """A reasonable folder to offer; never created or used until the operator accepts it."""

    return _user_data_dir(environ, system_name, home_dir) / "MotionLibrary"


def load_library_root(
    *,
    environ: Mapping[str, str] | None = None,
    system_name: str | None = None,
    home_dir: str | Path | None = None,
) -> str:
    """The configured root, or ``""`` when none was chosen (or the pointer file is unreadable)."""

    environment = os.environ if environ is None else environ
    override = str(environment.get(ENV_OVERRIDE) or "").strip()
    if override:
        return override
    try:
        payload = json.loads(
            config_path(environ=environ, system_name=system_name, home_dir=home_dir).read_text(
                encoding="utf-8"
            )
        )
    except (OSError, ValueError):
        return ""
    value = payload.get(ROOT_KEY) if isinstance(payload, dict) else ""
    return value.strip() if isinstance(value, str) else ""


def save_library_root(
    root: str | Path,
    *,
    environ: Mapping[str, str] | None = None,
    system_name: str | None = None,
    home_dir: str | Path | None = None,
) -> Path:
    """Validate and remember ``root`` (raises ``LibraryRootError`` for a relative or in-repository folder)."""

    resolved = validate_library_root(root)
    atomic_write_json(
        config_path(environ=environ, system_name=system_name, home_dir=home_dir),
        {"schema": "stablenew.motion-library-config", "version": 1, ROOT_KEY: str(resolved)},
        indent=2,
    )
    return resolved


__all__ = [
    "CONFIG_NAME",
    "ENV_OVERRIDE",
    "config_path",
    "load_library_root",
    "save_library_root",
    "suggested_library_root",
]
